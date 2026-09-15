"""Approvals API（IR-09：POST /runs/{id}/approve，FR-HITL-04/05/06）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, get_run_manager
from app.services.app_context import AppContext
from app.services.run_manager import RunConflict, RunManager
from app.storage import repositories as repo

router = APIRouter(tags=["approvals"])


class ApprovalIn(BaseModel):
    decision: str = Field(
        description="approve_once | approve_always | approve | reject | continue | resume"
        "（interactive 模式推荐 approve_once/approve_always；pause 打断恢复用 resume）"
    )
    note: str = ""
    by: str = "user"


@router.post("/runs/{run_id}/approve")
async def submit_approval(
    run_id: str,
    payload: ApprovalIn,
    ctx: AppContext = Depends(get_ctx),
    manager: RunManager = Depends(get_run_manager),
):
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
    if run.status not in {"waiting_approval", "needs_human"}:
        raise HTTPException(status_code=409, detail=f"运行当前状态为 {run.status}，不在等待审批状态")
    try:
        await manager.submit_approval(run_id, payload.decision, payload.note, payload.by)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "decision": payload.decision}


@router.get("/runs/{run_id}/approvals")
async def list_approvals(run_id: str, ctx: AppContext = Depends(get_ctx)):
    """审批留痕查询（可审计，FR-HITL-06）。"""
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        rows = await repo.list_approvals(session, run_id)
    return {
        "approvals": [
            {
                "id": a.id,
                "tool": a.tool,
                "arguments": a.arguments,
                "risk_level": a.risk_level,
                "reason": a.reason,
                "status": a.status,
                "scope": getattr(a, "scope", "once"),
                "consumed": bool(getattr(a, "consumed", False)),
                "decided_by": a.decided_by,
                "note": a.note,
                "requested_at": a.requested_at.isoformat() if a.requested_at else None,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a in rows
        ]
    }
