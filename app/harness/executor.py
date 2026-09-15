"""ToolExecutor：工具执行器（校验链 + 策略决策 + 重试 + 追踪）。

对应需求：FR-POL-01（校验链）、FR-CAP-05（最小权限）、FR-HARNESS-06（统一重试）、
FR-HITL-01~05（审批与中断）、FR-CODE-04（先 Plan 后修改的强制性约束）。
"""
from __future__ import annotations

import asyncio
import json
import time

from pydantic import ValidationError

from app.config import Settings
from app.harness.approval import ApprovalManager, ApprovalRequired
from app.harness.permission import WRITE_TOOLS
from app.harness.policy import PolicyEngine
from app.harness.registry import ToolContext, ToolError, ToolRegistry
from app.harness.retry import RetryManager
from app.observability.tracing import TraceManager
from app.schemas.events import EventType
from app.schemas.tool import PolicyAction, PolicyDecision, ToolCall, ToolResult

# interactive 模式下需要逐步确认的关键操作（写文件 / 删除 / 执行命令）
STEP_CONFIRM_TOOLS = {"edit_file", "create_file", "apply_patch", "delete_file", "run_command"}


class ToolExecutor:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ToolRegistry,
        policy: PolicyEngine,
        approvals: ApprovalManager,
        tracer: TraceManager,
        retry: RetryManager | None = None,
    ):
        self.settings = settings
        self.registry = registry
        self.policy = policy
        self.approvals = approvals
        self.tracer = tracer
        self.retry = retry or RetryManager(max_attempts=2, base_delay=0.3)

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """执行工具调用，全程返回 ToolResult（除 ApprovalRequired 外不抛异常）。"""
        started = time.perf_counter()
        tool = self.registry.get(call.name)
        if tool is None:
            return await self._finalize(
                ctx,
                call,
                ToolResult(ok=False, error=f"工具未注册: {call.name}", decision=PolicyAction.REJECT),
                started,
            )

        # ---------- 1) Schema Validation ----------
        try:
            validated = tool.input_model.model_validate(call.arguments or {})
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
            return await self._finalize(
                ctx,
                call,
                ToolResult(
                    ok=False,
                    error=f"参数校验失败: {msg}",
                    decision=PolicyAction.EXECUTE,
                    risk_level=tool.defn.risk_level,
                ),
                started,
            )

        # ---------- 2) 强制性业务规则（FR-CODE-04：先 Plan 后修改） ----------
        if ctx.agent == "coder" and call.name in WRITE_TOOLS and not ctx.session.plan:
            return await self._finalize(
                ctx,
                call,
                ToolResult(
                    ok=False,
                    error=(
                        "在执行任何文件修改之前，必须先调用 update_plan 记录修改计划"
                        "（approach / steps / files_to_change），然后再进行修改。"
                    ),
                    decision=PolicyAction.REJECT,
                    risk_level=tool.defn.risk_level,
                ),
                started,
            )

        # ---------- 3) Policy Validation + Permission Check + Risk Evaluation ----------
        decision = self.policy.evaluate(ctx.agent, tool.defn, validated.model_dump())
        if decision.action == PolicyAction.REJECT:
            return await self._finalize(
                ctx,
                call,
                ToolResult(
                    ok=False,
                    error=f"策略拒绝: {decision.reason}",
                    decision=PolicyAction.REJECT,
                    risk_level=decision.risk_level,
                ),
                started,
            )

        # ---------- 3.5) 运行级审批模式（interactive：关键操作逐步确认） ----------
        run_mode = await self.approvals.mode_for(ctx.run_id)
        if (
            run_mode == "interactive"
            and call.name in STEP_CONFIRM_TOOLS
            and decision.action == PolicyAction.EXECUTE
        ):
            decision = PolicyDecision(
                action=PolicyAction.APPROVAL,
                reason=f"逐步确认模式：{call.name} 为关键操作，需人工确认",
                risk_level=decision.risk_level,
            )

        # ---------- 4) Approval（FR-HITL） ----------
        if decision.action == PolicyAction.APPROVAL:
            status, note = await self.approvals.resolve(
                run_id=ctx.run_id,
                tool=call.name,
                arguments=call.arguments,
                risk_level=decision.risk_level.value,
                reason=decision.reason,
                per_call=(run_mode == "interactive"),
            )
            if status == "waiting":
                # 需要人工审批 → 抛出以触发图中断
                raise ApprovalRequired(ctx.run_id, call.name, call.arguments, decision.risk_level.value, decision.reason)
            if status == "rejected":
                return await self._finalize(
                    ctx,
                    call,
                    ToolResult(
                        ok=False,
                        error=f"人工审批已拒绝: {note or decision.reason}",
                        decision=PolicyAction.APPROVAL,
                        risk_level=decision.risk_level,
                    ),
                    started,
                )
            # approved → 继续执行

        # ---------- 5) Execute（带瞬态错误重试） ----------
        if ctx.emit:
            ctx.emit(EventType.TOOL_CALL.value, f"{call.name}({self._brief_args(call.arguments)})", {"tool": call.name})

        async def _run() -> ToolResult:
            return await tool.run(call.arguments, ctx)

        try:
            result = await self.retry.run(
                _run,
                retryable=lambda exc: isinstance(exc, (OSError, asyncio.TimeoutError)),
            )
        except ToolError as exc:
            result = ToolResult(ok=False, error=str(exc), risk_level=tool.defn.risk_level)
        except asyncio.TimeoutError:
            result = ToolResult(ok=False, error=f"工具执行超时: {call.name}", risk_level=tool.defn.risk_level)
        except Exception as exc:  # noqa: BLE001 —— 工具层异常统一转为失败结果
            result = ToolResult(
                ok=False,
                error=f"工具执行异常: {type(exc).__name__}: {exc}",
                risk_level=tool.defn.risk_level,
            )

        result.risk_level = tool.defn.risk_level
        return await self._finalize(ctx, call, result, started)

    # =====================================================

    async def _finalize(self, ctx: ToolContext, call: ToolCall, result: ToolResult, started: float) -> ToolResult:
        if result.duration_ms == 0.0:
            result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        await self.tracer.record_tool_run(
            run_id=ctx.run_id,
            agent=ctx.agent,
            tool=call.name,
            arguments=self._safe_args(call.arguments),
            ok=result.ok,
            duration_ms=result.duration_ms,
            risk_level=result.risk_level.value,
            decision=result.decision.value,
            error=result.error or "",
        )
        if ctx.emit:
            if result.ok:
                summary = str(result.data)
                ctx.emit(EventType.TOOL_RESULT.value, f"{call.name} ok: {summary[:160]}", {"tool": call.name, "ok": True})
            else:
                ctx.emit(
                    EventType.TOOL_RESULT.value,
                    f"{call.name} failed: {(result.error or '')[:160]}",
                    {"tool": call.name, "ok": False},
                )
        return result

    @staticmethod
    def _brief_args(args: dict) -> str:
        try:
            text = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(args)
        return text[:120]

    def _safe_args(self, args: dict) -> dict:
        """追踪入库前截断参数中的大文本。"""
        safe: dict = {}
        for key, value in (args or {}).items():
            if isinstance(value, str) and len(value) > 500:
                safe[key] = value[:500] + f"...({len(value)} chars)"
            elif isinstance(value, (dict, list)):
                text = self._brief_args(value if isinstance(value, dict) else {"items": value[:20]})
                safe[key] = text
            else:
                safe[key] = value
        return safe
