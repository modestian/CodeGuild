"""Architect Agent：技术设计与 Task DAG（FR-ARCH-01~06）。

输出：技术方案 / 模块划分 / API 契约 / 数据模型 / 模块依赖 / Task DAG（无环校验）。
"""
from __future__ import annotations

import json

from app.agents.base import (
    agent_prompt,
    build_repo_overview,
    ctx_factory_for,
    dump_tasks,
    make_error,
    merged_errors,
    workspace_of,
)
from app.schemas.artifacts import Architecture
from app.schemas.events import EventType
from app.schemas.state import TaskDAGError, TaskRecord, TaskStatus, compute_ready_tasks, validate_task_dag
from app.services.app_context import AppContext
from app.storage import repositories as repo


def _brief(state: dict, workspace, feedback: str = "") -> str:
    requirements_json = json.dumps(state.get("requirements") or {}, ensure_ascii=False)[:6000]
    overview = build_repo_overview(workspace, max_chars=2000)
    brief = (
        f"## 产品需求（结构化）\n{requirements_json}\n\n"
        f"## 仓库现状\n{overview}\n\n"
        "## 交付目标\n"
        "产出技术设计方案与开发任务列表（Task DAG）。任务要求：\n"
        "- 每个任务可被 Coding Agent 独立完成（单一职责、可验证）\n"
        "- depends_on 必须引用列表中已存在的任务 id，禁止循环依赖\n"
        "- 为每个任务给出 acceptance_criteria（便于后续 Review）\n"
    )
    if feedback:
        brief += f"\n## 上次输出问题（必须修复）\n{feedback}\n"
    return brief


async def run_architect(app: AppContext, state: dict) -> dict:
    run_id = state["run_id"]
    workspace = workspace_of(state)

    feedback = ""
    architecture: dict | None = None
    for _attempt in range(2):
        result = await app.runtime.run(
            run_id=run_id,
            agent="architect",
            system_prompt=agent_prompt("architect"),
            task_brief=_brief(state, workspace, feedback),
            ctx_factory=ctx_factory_for(app, state, "architect"),
            output_schema=Architecture,
            mode="single",
        )
        if result.status != "finished" or not result.final_output:
            detail = result.error or result.stopped_reason or "unknown"
            await app.tracer.emit(
                run_id, EventType.RUN_FAILED, f"Architect Agent 失败: {detail[:200]}", agent="architect"
            )
            return {
                "current_agent": "architect",
                "run_status": "failed",
                "fail_reason": f"架构设计失败: {detail[:300]}",
                "errors": merged_errors(state, make_error("architect", detail)),
            }
        candidate = result.final_output
        try:
            tasks = [
                TaskRecord(
                    id=item["id"],
                    title=item.get("title", item["id"]),
                    description=item.get("description", ""),
                    dependencies=list(item.get("depends_on") or []),
                    priority=item.get("priority", "high"),
                    acceptance_criteria=list(item.get("acceptance_criteria") or []),
                )
                for item in (candidate.get("tasks") or [])
            ]
            if not tasks:
                raise TaskDAGError("任务列表为空")
            validate_task_dag(tasks)
            architecture = candidate
            break
        except (TaskDAGError, KeyError, TypeError) as exc:
            feedback = f"Task DAG 校验失败: {exc}。请修正 tasks 后重新输出完整 JSON。"
            await app.tracer.emit(
                run_id, EventType.LOG, f"Architect 输出校验失败，要求修复: {exc}", agent="architect"
            )

    if architecture is None:
        return {
            "current_agent": "architect",
            "run_status": "failed",
            "fail_reason": "架构设计输出无法通过 Task DAG 校验",
            "errors": merged_errors(state, make_error("architect", "Task DAG 校验失败（已要求修复一次）")),
        }

    # 持久化架构产物
    artifact = app.save_artifact(run_id, "architecture", architecture)

    # Task DAG 初始化（PENDING → 计算 READY）
    tasks = [
        TaskRecord(
            id=item["id"],
            title=item.get("title", item["id"]),
            description=item.get("description", ""),
            dependencies=list(item.get("depends_on") or []),
            priority=item.get("priority", "high"),
            acceptance_criteria=list(item.get("acceptance_criteria") or []),
        )
        for item in architecture.get("tasks") or []
    ]
    ready = compute_ready_tasks(tasks)
    for t in tasks:
        if t.id in ready:
            t.status = TaskStatus.READY

    async with app.database.session() as session:
        await repo.sync_tasks(session, run_id, tasks)

    await app.tracer.emit(
        run_id, EventType.TASKS_GENERATED, f"Architect generated {len(tasks)} tasks.", agent="architect"
    )
    for t in tasks:
        if t.id in ready:
            await app.tracer.emit(run_id, EventType.TASK_READY, f"Task {t.id} ready.", agent="architect")

    return {
        "architecture": architecture,
        "task_dag": dump_tasks(tasks),
        "ready_tasks": ready,
        "current_agent": "architect",
        "artifacts": {**(state.get("artifacts") or {}), "architecture": artifact},
        "run_status": "running",
        "dev_cycle_done": False,
        "needs_human": False,
    }
