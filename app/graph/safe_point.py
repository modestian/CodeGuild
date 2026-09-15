"""HITL 安全点：人工打断（pause/resume）统一处理。

- 用户在任意时刻请求打断 → 图在下一个安全点（Supervisor 调度前 / 任务调度器）挂起
- 恢复时携带可选补充需求（guidance），恢复后注入 Agent 上下文
- interrupt 恢复后（含节点 replay）才清除标志，保证重放幂等
"""
from __future__ import annotations

import uuid

from langgraph.types import interrupt

from app.schemas.events import EventType
from app.services.app_context import AppContext


async def pause_safe_point(app: AppContext, state: dict, where: str = "") -> None:
    """若用户请求打断：在当前安全点挂起；恢复后清除标志并注入补充需求。"""
    run_id = state["run_id"]
    if not app.controls.pause_requested(run_id):
        return
    payload = {
        "type": "pause",
        "run_id": run_id,
        "approval_id": uuid.uuid4().hex,  # 每次挂起唯一，供前端区分多次请求
        "reason": "用户请求打断运行" + (f"（{where}）" if where else "") + "，可在恢复时补充新需求",
        "current_agent": state.get("current_agent", ""),
        "options": ["resume", "reject"],
    }
    resume_value = interrupt(payload)
    # interrupt 恢复后（含 replay）：清除标志，保证幂等
    app.controls.clear_pause(run_id)
    if isinstance(resume_value, str):
        resume_value = {"guidance": resume_value}
    resume_value = resume_value or {}
    text = str(resume_value.get("guidance") or resume_value.get("text") or "").strip()
    if text:
        await app.guidance.add(run_id, text, source="user")
    await app.tracer.emit(
        run_id,
        EventType.PAUSE_RESUMED,
        "已恢复运行" + (f"，并补充需求：{text[:120]}" if text else ""),
        agent="human",
        data={"guidance": text},
    )
