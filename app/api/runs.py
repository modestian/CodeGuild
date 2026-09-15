"""Runs API（IR-02 ~ IR-08，IR-10 事件流）。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, get_run_manager
from app.schemas.events import EventType
from app.services.app_context import AppContext
from app.services.run_manager import RunConflict, RunManager
from app.storage import repositories as repo

router = APIRouter(tags=["runs"])

TERMINAL_STATUSES = {"completed", "failed", "rejected", "cancelled"}


class RunCreate(BaseModel):
    request: str = Field(min_length=1, description="自然语言开发需求")
    mode: str = Field(
        default="auto",
        description="请求模式：auto（LLM 意图判定）| query（只读问答）| develop（开发闭环）",
    )
    approval_mode: str = Field(
        default="auto", description="审批模式：auto（仅高风险审批）| interactive（关键操作逐步确认）"
    )


def _run_out(run, project=None) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "request": run.request,
        "status": run.status,
        "current_agent": run.current_agent,
        "mode": run.mode,
        "approval_mode": getattr(run, "approval_mode", "") or "auto",
        "branch": run.branch,
        "workspace_path": run.workspace_path,
        "error": run.error,
        "metrics": run.metrics or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "project": {"id": project.id, "name": project.name} if project else None,
    }


# =========================================================
# IR-02：POST /projects/{id}/runs
# =========================================================


@router.post("/projects/{project_id}/runs")
async def create_run(
    project_id: str,
    payload: RunCreate,
    ctx: AppContext = Depends(get_ctx),
    manager: RunManager = Depends(get_run_manager),
):
    async with ctx.database.session() as session:
        project = await repo.get_project(session, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        approval_mode = (payload.approval_mode or "auto").lower().strip()
        if approval_mode not in {"auto", "interactive"}:
            raise HTTPException(status_code=422, detail=f"非法审批模式: {approval_mode}")
        mode = (payload.mode or "auto").lower().strip()
        if mode not in {"auto", "query", "develop"}:
            raise HTTPException(status_code=422, detail=f"非法请求模式: {mode}")
        run = await repo.create_run(session, project_id, payload.request, mode=mode, approval_mode=approval_mode)
    try:
        await manager.start_run(run.id)
    except Exception as exc:  # noqa: BLE001 —— 工作区创建失败
        async with ctx.database.session() as session:
            await repo.update_run(session, run.id, status="failed", error=str(exc)[:2000])
        raise HTTPException(status_code=400, detail=f"运行启动失败: {exc}") from exc
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run.id)
    return {"run": _run_out(run, project)}


# =========================================================
# IR-03：GET /runs/{id}
# =========================================================


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        project = await repo.get_project(session, run.project_id)
        metrics = await repo.aggregate_metrics(session, run_id)
    out = _run_out(run, project)
    merged_metrics = dict(out.get("metrics") or {})
    merged_metrics.update({k: v for k, v in metrics.items() if k not in merged_metrics})
    out["metrics"] = merged_metrics
    return out


# =========================================================
# IR-04：GET /runs/{id}/state
# =========================================================


@router.get("/runs/{run_id}/state")
async def get_state(run_id: str, ctx: AppContext = Depends(get_ctx), manager: RunManager = Depends(get_run_manager)):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    try:
        graph = manager._get_graph()
        snapshot = await graph.aget_state(manager._config(run_id))
        values = dict(snapshot.values or {})
        return {
            "state": values,
            "next": list(snapshot.next or []),
            "pending_approval": await manager.get_pending_payload_async(run_id),
        }
    except Exception:  # noqa: BLE001 —— 无 Checkpoint 时返回空状态
        return {"state": {}, "next": [], "pending_approval": None}


# =========================================================
# IR-05 / IR-10：GET /runs/{id}/events（SSE）
# =========================================================


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    follow: bool = Query(default=True, description="是否保持连接持续推送"),
    after_seq: int = Query(default=-1, description="从该序号之后开始（断线重放）"),
    ctx: AppContext = Depends(get_ctx),
):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")

    async def event_generator():
        last_seq = after_seq
        # 1) 补发持久化事件
        async with ctx.database.session() as session:
            rows = await repo.list_events(session, run_id, after_seq=last_seq)
        for row in rows:
            frame = {
                "id": f"{row.id}",
                "run_id": run_id,
                "seq": row.seq,
                "type": row.type,
                "agent": row.agent,
                "message": row.message,
                "data": row.data or {},
                "ts": row.ts,
            }
            last_seq = row.seq
            yield f"event: {row.type}\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n"

        if not follow:
            return

        # 2) 实时事件
        queue = ctx.bus.subscribe(run_id)
        try:
            terminal = run.status in TERMINAL_STATUSES
            while True:
                if terminal:
                    # 运行已结束：重放完即可关闭
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    async with ctx.database.session() as session:
                        current = await repo.get_run(session, run_id)
                    terminal = bool(current and current.status in TERMINAL_STATUSES)
                    if terminal:
                        # 补发结束前的事件
                        async with ctx.database.session() as session:
                            rows = await repo.list_events(session, run_id, after_seq=last_seq)
                        for row in rows:
                            frame = {
                                "id": f"{row.id}", "run_id": run_id, "seq": row.seq, "type": row.type,
                                "agent": row.agent, "message": row.message, "data": row.data or {}, "ts": row.ts,
                            }
                            last_seq = row.seq
                            yield f"event: {row.type}\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n"
                        break
                    continue
                if event is None:
                    break
                if event.seq <= last_seq:
                    continue
                last_seq = event.seq
                yield event.sse()
        finally:
            ctx.bus.unsubscribe(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# =========================================================
# IR-06：POST /runs/{id}/resume
# =========================================================


class ResumeIn(BaseModel):
    resume: dict[str, Any] = Field(default_factory=dict, description="恢复到中断点的载荷")


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    payload: ResumeIn,
    ctx: AppContext = Depends(get_ctx),
    manager: RunManager = Depends(get_run_manager),
):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    try:
        await manager.resume(run_id, payload.resume)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"resumed": True, "run_id": run_id}


# =========================================================
# IR-07：GET /runs/{id}/tasks
# =========================================================


@router.get("/runs/{run_id}/tasks")
async def list_tasks(run_id: str, ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        tasks = await repo.list_tasks(session, run_id)
    return {
        "tasks": [
            {
                "id": t.task_id,
                "title": t.title,
                "description": t.description,
                "dependencies": t.dependencies or [],
                "status": t.status,
                "assigned_agent": t.assigned_agent,
                "priority": t.priority,
                "acceptance_criteria": t.acceptance_criteria or [],
                "attempts": t.attempts,
                "result_summary": t.result_summary,
                "error": t.error,
            }
            for t in tasks
        ]
    }


# =========================================================
# IR-08：GET /runs/{id}/diff
# =========================================================


@router.get("/runs/{run_id}/diff")
async def get_diff(
    run_id: str,
    stat_only: bool = Query(default=False),
    ctx: AppContext = Depends(get_ctx),
):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    if not run.workspace_path:
        raise HTTPException(status_code=400, detail="运行尚无工作区")
    workspace = Path(run.workspace_path)
    if not workspace.exists():
        raise HTTPException(status_code=400, detail="工作区不存在")
    try:
        diff = await ctx.workspaces.full_diff(workspace, stat_only=stat_only)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成 diff 失败: {exc}") from exc
    return {"diff": diff, "branch": run.branch, "workspace": run.workspace_path}


# =========================================================
# FR-EVAL-08：GET /runs/{id}/metrics
# =========================================================


@router.get("/runs/{run_id}/metrics")
async def get_metrics(run_id: str, ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        metrics = await repo.aggregate_metrics(session, run_id)
    metrics.update(run.metrics or {})
    return metrics


# =========================================================
# 运行中人工交互（HITL 增强）：追加需求 / 审批模式 / 取消
# =========================================================


class GuidanceIn(BaseModel):
    text: str = Field(min_length=1, description="用户补充要求（将在 Agent 下一步注入上下文）")


@router.post("/runs/{run_id}/guidance")
async def submit_guidance(
    run_id: str,
    payload: GuidanceIn,
    ctx: AppContext = Depends(get_ctx),
):
    """运行中追加需求：登记后由 Agent 执行循环在下一步领取并注入。"""
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"运行已结束（{run.status}），无法追加需求")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="补充要求不能为空")
    item = await ctx.guidance.add(run_id, text, source="user")
    await ctx.tracer.emit(
        run_id,
        EventType.GUIDANCE_RECEIVED,
        f"用户补充要求：{text[:160]}",
        agent="human",
        data={"guidance_id": item.get("id")},
    )
    return {"accepted": True, "guidance": item}


@router.get("/runs/{run_id}/guidance")
async def list_guidance(run_id: str, ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    items = await ctx.guidance.list(run_id)
    return {"guidance": items}


class ApprovalModeIn(BaseModel):
    mode: str = Field(description="auto | interactive")


@router.post("/runs/{run_id}/approval_mode")
async def set_approval_mode(
    run_id: str,
    payload: ApprovalModeIn,
    manager: RunManager = Depends(get_run_manager),
):
    """切换运行级审批模式（运行中可随时切换）。"""
    try:
        await manager.set_approval_mode(run_id, payload.mode)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "approval_mode": payload.mode.lower().strip()}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, manager: RunManager = Depends(get_run_manager)):
    """取消运行（人工终止）：执行中打断图任务，挂起态直接标记取消。"""
    try:
        await manager.cancel(run_id)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "run_id": run_id}


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, manager: RunManager = Depends(get_run_manager)):
    """人工打断（HITL）：下一个安全点（Supervisor 调度前）暂停，可在恢复时补充需求。

    恢复方式：POST /runs/{id}/approve（decision=resume，note=补充需求）或 /runs/{id}/resume。
    """
    try:
        await manager.request_pause(run_id)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "run_id": run_id, "note": "打断请求已登记，将在下一个安全点暂停"}
