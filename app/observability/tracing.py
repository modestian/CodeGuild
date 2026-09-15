"""TraceManager：全链路追踪与事件发布。

对应需求：FR-OBS-01~03（所有 Agent Run 可追踪；记录 model/agent/tool/latency/token/cost/error/retry；
由 TraceManager 统一采集与上报）。LangSmith / OpenTelemetry / Prometheus 接入为 V2（FR-OBS-04/05）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import Settings
from app.observability import events as obs_events
from app.schemas.events import EventType, RunEvent
from app.storage import repositories as repo
from app.storage.db import Database

logger = logging.getLogger("copilot.trace")


class TraceManager:
    """统一追踪：DB 落库 + EventBus 推送 + 结构化日志。"""

    def __init__(self, database: Database, settings: Settings, bus: Optional[obs_events.EventBus] = None):
        self.database = database
        self.settings = settings
        self.bus = bus or obs_events.bus
        self._seq_cache: dict[str, int] = {}

    # =====================================================
    # 事件
    # =====================================================

    async def emit(
        self,
        run_id: str,
        type: EventType,
        message: str = "",
        agent: str = "",
        data: Optional[dict[str, Any]] = None,
    ) -> RunEvent:
        seq = await self._next_seq(run_id)
        event = RunEvent(run_id=run_id, seq=seq, type=type, agent=agent, message=message, data=data or {})
        try:
            async with self.database.session() as session:
                await repo.add_event(session, event)
        except Exception:  # 事件落库失败不影响主流程
            logger.exception("事件持久化失败: %s", event.type.value)
        self.bus.publish(event)
        if message:
            logger.info("[%s][%s] %s", run_id[:8], agent or "-", message)
        return event

    async def _next_seq(self, run_id: str) -> int:
        if run_id not in self._seq_cache:
            async with self.database.session() as session:
                self._seq_cache[run_id] = await repo.next_event_seq(session, run_id)
        seq = self._seq_cache[run_id]
        self._seq_cache[run_id] = seq + 1
        return seq

    def close_run(self, run_id: str) -> None:
        self.bus.close(run_id)

    # =====================================================
    # Agent / Tool / Checkpoint 追踪
    # =====================================================

    async def start_agent_run(self, run_id: str, agent: str, task_id: str, model: str) -> Optional[int]:
        try:
            async with self.database.session() as session:
                return await repo.start_agent_run(session, run_id, agent, task_id, model)
        except Exception:
            logger.exception("AgentRun 记录失败")
            return None

    async def finish_agent_run(
        self,
        agent_run_id: Optional[int],
        *,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        steps: int = 0,
        tool_calls: int = 0,
        error: str = "",
    ) -> None:
        if agent_run_id is None:
            return
        try:
            async with self.database.session() as session:
                await repo.finish_agent_run(
                    session,
                    agent_run_id,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    steps=steps,
                    tool_calls=tool_calls,
                    error=error,
                )
        except Exception:
            logger.exception("AgentRun 更新失败")

    async def record_tool_run(
        self,
        run_id: str,
        agent: str,
        tool: str,
        arguments: dict[str, Any],
        ok: bool,
        duration_ms: float,
        risk_level: str,
        decision: str,
        error: str = "",
    ) -> None:
        try:
            async with self.database.session() as session:
                await repo.add_tool_run(
                    session, run_id, agent, tool, arguments, ok, duration_ms, risk_level, decision, error
                )
        except Exception:
            logger.exception("ToolRun 记录失败")

    async def record_checkpoint(self, run_id: str, node: str, iteration: int, current_agent: str) -> None:
        try:
            async with self.database.session() as session:
                await repo.add_checkpoint_meta(session, run_id, node, iteration, current_agent)
        except Exception:
            logger.exception("Checkpoint 记录失败")
