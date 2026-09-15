"""ApprovalManager：人工审批（Human-in-the-loop）管理。

对应需求：FR-HITL-01~06：
- 高风险操作通过 LangGraph interrupt() 中断并等待人工审批
- 审批通过（YES）→ 执行；拒绝（NO）→ Reject；审批后可从中断点恢复
- 审批记录持久化（approvals 表），可查询与审计

审批模式（per-run）：
- auto：仅高风险/强制审批工具中断（默认）
- interactive：关键操作（写文件、执行命令）逐步确认——每次调用中断，
  用户可选择「批准本次（once）」或「批准后续免问（always）」；once 批准被消费后
  同工具再次调用会重新询问。
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import Settings
from app.storage import repositories as repo
from app.storage.db import Database


class ApprovalRequired(Exception):
    """工具调用需要人工审批：由执行层向上抛出，触发图中断（interrupt）。"""

    def __init__(self, run_id: str, tool: str, arguments: dict[str, Any], risk_level: str, reason: str):
        super().__init__(f"工具 {tool} 需要人工审批: {reason}")
        self.run_id = run_id
        self.tool = tool
        self.arguments = arguments
        self.risk_level = risk_level
        self.reason = reason


class ApprovalManager:
    """审批决策查询与申请（含运行级审批模式缓存）。"""

    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self._modes: dict[str, str] = {}

    # ---------- 运行级审批模式 ----------

    async def mode_for(self, run_id: str) -> str:
        """解析运行的审批模式（内存缓存；miss 时从 DB 读取，服务重启后可恢复）。"""
        mode = self._modes.get(run_id)
        if mode:
            return mode
        try:
            async with self.database.session() as session:
                run = await repo.get_run(session, run_id)
            mode = str(getattr(run, "approval_mode", "") or "auto") if run else "auto"
        except Exception:  # noqa: BLE001 —— 查询失败按默认 auto 处理
            mode = "auto"
        self._modes[run_id] = mode
        return mode

    def set_mode(self, run_id: str, mode: str) -> None:
        self._modes[run_id] = mode

    def forget(self, run_id: str) -> None:
        self._modes.pop(run_id, None)

    async def resolve(
        self,
        run_id: str,
        tool: str,
        arguments: dict[str, Any],
        risk_level: str,
        reason: str,
        per_call: bool = False,
    ) -> tuple[str, str]:
        """解析审批状态。

        返回 (status, note)：
        - ("approved", note)  已批准 → 执行
        - ("rejected", note)  已拒绝 → Reject
        - ("waiting", note)   无记录/待审批 → 已登记 pending 请求（调用方应触发中断）

        per_call=True（interactive 模式）：一次性批准/拒绝被消费后，同工具再次调用
        重新创建 pending 请求（每次询问）；scope=always 的批准则持续免问。
        """
        async with self.database.session() as session:
            record = await repo.find_approval_for_tool(session, run_id, tool)
            if record is None:
                await repo.create_approval_request(session, run_id, tool, arguments, risk_level, reason)
                return "waiting", "已创建待审批请求"
            if record.status == "pending":
                return "waiting", "审批待处理"
            if record.consumed:
                if record.scope == "always":
                    return record.status, record.note
                # 一次性决定已消费 → 新一轮询问
                await repo.create_approval_request(session, run_id, tool, arguments, risk_level, reason)
                return "waiting", "已创建新的待审批请求"
            if per_call:
                # 未消费的决定：本次调用消费之（once 语义）
                await repo.mark_approval_consumed(session, record.id)
            return record.status, record.note

    async def record_decision(
        self,
        run_id: str,
        tool: str,
        decision: str,
        note: str = "",
        decided_by: str = "user",
        scope: str = "always",
    ) -> None:
        """记录对某工具审批的最新决定（approve / reject）。

        scope=once：仅本次调用有效（消费后重新询问）；always：本次运行内持续生效。
        """
        status = (
            "approved"
            if decision in {"approve", "approved", "yes", "approve_once", "approve_always"}
            else "rejected"
        )
        if decision == "approve_once":
            scope = "once"
        elif decision == "approve_always":
            scope = "always"
        async with self.database.session() as session:
            record = await repo.find_approval_for_tool(session, run_id, tool)
            if record is None:
                record = await repo.create_approval_request(session, run_id, tool, {}, "HIGH", "人工审批")
            await repo.decide_approval(session, record.id, status, decided_by, note, scope=scope)
