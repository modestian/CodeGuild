"""AgentRuntime：统一 Agent 执行循环（Build Context → Model Call → Decision → Tool → Observation）。

对应需求：FR-EXEC-01~04（标准循环 / 停止条件 / 防无限循环 / Final 决策）、
FR-HARNESS-01~05（所有 Agent 共用同一 Harness）。

工具调用协议：原生 function calling（OpenAI 兼容 tools / tool_calls），
assistant 的 tool_calls 消息与 tool 结果消息严格配对（tool_call_id），
保证与 DeepSeek / OpenAI 等提供方的严格校验兼容。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Optional

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.harness.approval import ApprovalRequired
from app.harness.context import ContextManager
from app.harness.executor import ToolExecutor
from app.harness.llm import LLMClient, StructuredOutputError, extract_json
from app.harness.observation import ObservationAdapter
from app.harness.permission import PermissionManager
from app.harness.registry import ToolContext, ToolRegistry
from app.harness.session import RuntimeSession
from app.observability.tracing import TraceManager
from app.schemas.events import EventType
from app.schemas.tool import AgentDecision, ToolCall

logger = logging.getLogger("copilot.runtime")

ContextFactory = Callable[[RuntimeSession], ToolContext]


class AgentRunResult(BaseModel):
    status: str  # finished | failed | awaiting_approval | stopped
    final_output: Optional[dict[str, Any]] = None
    error: str = ""
    stopped_reason: str = ""
    session_id: str = ""


class AgentRuntime:
    """统一运行时：所有 Agent 通过本类执行（FR-HARNESS-01/04）。

    预算计数器（steps / tokens / cost / tool_failures / 墙钟）按「执行段」管理：
    coder / tester / reviewer 跨任务重试、修复轮次与人工「继续迭代」复用同一会话，
    上一段执行已结束时（finished / stopped / failed）在段开始时重置计数器、保留对话记忆，
    避免续跑时在循环入口被 _stop_reason 立即判停（token 到顶 / 轮次上限后"继续即失败"）。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        executor: ToolExecutor,
        context_manager: ContextManager,
        observation: ObservationAdapter,
        permissions: PermissionManager,
        tracer: TraceManager,
        session_store: SessionStore,
        llm_factory: Callable[[str], LLMClient],
        registry: Optional[ToolRegistry] = None,
        guidance: Optional[Any] = None,  # GuidanceManager（运行中人工补充要求）
    ):
        self.settings = settings
        self.executor = executor
        self.context = context_manager
        self.observation = observation
        self.permissions = permissions
        self.tracer = tracer
        self.sessions = session_store
        self.llm_factory = llm_factory
        self.registry = registry or getattr(executor, "registry", None)
        self.guidance = guidance

    # =====================================================
    # 主循环
    # =====================================================

    async def run(
        self,
        *,
        run_id: str,
        agent: str,
        system_prompt: str,
        task_brief: str,
        ctx_factory: ContextFactory,
        output_schema: Optional[type[BaseModel]] = None,
        mode: str = "agentic",  # agentic（工具循环） | single（单次结构化输出）
        session: Optional[RuntimeSession] = None,
        memory_excerpt: str = "",
        working_memory_text: str = "",
        task_id: str = "",
    ) -> AgentRunResult:
        profile = self.permissions.get_profile(agent)
        llm = self.llm_factory(agent)
        session = session or RuntimeSession(
            session_id=f"{run_id}:{agent}:{task_id or 'main'}",
            run_id=run_id,
            agent=agent,
            task_id=task_id,
        )

        # ---------- 执行段预算（会话复用：避免"继续迭代"立即命中停止条件） ----------
        prev_status = session.status
        if prev_status == "awaiting_approval":
            # 审批恢复属同一执行段：steps / tokens 预算继续累计，但人工等待不计入 Agent 墙钟
            session.started_ts = time.time()
        elif prev_status in {"finished", "stopped", "failed"} and session.messages:
            await self._reset_execution_budget(session, agent, prev_status)
        session.status = "running"

        if not session.messages:
            session.messages = self.context.initial_messages(
                system_prompt, task_brief, memory_excerpt, working_memory_text
            )

        agent_run_id = await self.tracer.start_agent_run(session.run_id, agent, task_id or session.task_id, llm.model)
        await self.tracer.emit(
            session.run_id,
            EventType.AGENT_STARTED,
            f"{agent} started" + (f" {task_id or session.task_id}" if (task_id or session.task_id) else ""),
            agent=agent,
        )

        try:
            if mode == "single":
                result = await self._run_single(llm, session, output_schema)
                return await self._finish(agent_run_id, session, result, agent)
            result = await self._run_agentic(llm, session, output_schema, ctx_factory, profile.max_steps, agent)
            if result.status == "awaiting_approval":
                await self.tracer.finish_agent_run(
                    agent_run_id,
                    status="awaiting_approval",
                    input_tokens=session.input_tokens,
                    output_tokens=session.output_tokens,
                    cost_usd=session.cost_usd,
                    steps=session.steps,
                    tool_calls=len(session.recent_tool_calls(1000)),
                )
                await self.tracer.emit(
                    session.run_id, EventType.APPROVAL_REQUIRED, f"{agent} awaiting human approval", agent=agent
                )
                return result
            return await self._finish(agent_run_id, session, result, agent)
        except StructuredOutputError as exc:
            error = f"结构化输出失败: {exc}"
            return await self._fail(agent_run_id, session, agent, "failed", error)
        except Exception as exc:  # noqa: BLE001 —— 运行时兜底，防止图崩溃
            logger.exception("AgentRuntime 执行异常")
            error = f"{type(exc).__name__}: {exc}"
            return await self._fail(agent_run_id, session, agent, "failed", error)

    # =====================================================

    async def _reset_execution_budget(self, session: RuntimeSession, agent: str, prev_status: str) -> None:
        """新执行段开始：保留对话记忆（messages / plan / changed_files），重置停止条件计数器。

        不重置的后果：上一段（token 到顶 / 轮次上限而 stopped）的累计值会让本次执行
        在循环入口被 _stop_reason 立即判停，表现为"继续迭代后立即失败且无任何动作"。
        """
        used = {
            "steps": session.steps,
            "tokens": session.input_tokens + session.output_tokens,
            "cost_usd": session.cost_usd,
            "tool_failures": session.tool_failures,
        }
        session.steps = 0
        session.tool_failures = 0
        session.input_tokens = 0
        session.output_tokens = 0
        session.cost_usd = 0.0
        session.error = ""
        session.final_output = None
        session.started_ts = time.time()
        self.sessions.save(session)
        await self.tracer.emit(
            session.run_id,
            EventType.LOG,
            f"{agent} 开始新的执行段：预算计数器已重置（上一段 status={prev_status}，"
            f"steps={used['steps']}，tokens={used['tokens']}，cost=${used['cost_usd']:.4f}）",
            agent=agent,
            data={"previous_segment": {**used, "status": prev_status}},
        )

    # =====================================================

    async def _run_single(
        self, llm: LLMClient, session: RuntimeSession, output_schema: Optional[type[BaseModel]]
    ) -> AgentRunResult:
        assert output_schema is not None, "single 模式必须提供 output_schema"
        messages = self.context.prepare(session)
        schema_model, response = await llm.complete_structured(messages, output_schema)
        self._account(session, response.usage.input_tokens, response.usage.output_tokens, response.cost_usd)
        session.steps += 1
        session.add_message("assistant", response.content)
        session.final_output = schema_model.model_dump()
        session.status = "finished"
        self.sessions.save(session)
        return AgentRunResult(status="finished", final_output=session.final_output, session_id=session.session_id)

    async def _run_agentic(
        self,
        llm: LLMClient,
        session: RuntimeSession,
        output_schema: Optional[type[BaseModel]],
        ctx_factory: ContextFactory,
        max_steps: int,
        agent: str,
    ) -> AgentRunResult:
        max_tokens = self.settings.agent_max_tokens
        max_cost = self.settings.agent_max_cost_usd
        max_wall = self.settings.agent_timeout_seconds
        max_failures = self.settings.agent_max_tool_failures
        tools = self._tool_specs_for(agent)

        while True:
            # ---------- 待审批调用恢复（中断安全）：优先执行未完成的工具调用批次 ----------
            # 排在停止条件之前：恢复后已获批的工具调用必须执行（否则"批准"后无任何动作即判停）
            if session.pending_calls:
                interrupted = await self._drain_pending_calls(session, ctx_factory)
                if interrupted is not None:
                    return interrupted
                continue

            # ---------- 停止条件（FR-EXEC-02/03） ----------
            reason = self._stop_reason(session, max_steps, max_tokens, max_cost, max_wall, max_failures)
            if reason:
                session.status = "stopped"
                self.sessions.save(session)  # 持久化停止状态：跨进程恢复时可识别为"上一段已结束"
                return AgentRunResult(status="stopped", stopped_reason=reason, session_id=session.session_id)

            # ---------- 用户补充要求注入（运行中人工干预，HITL） ----------
            # 仅在待办工具调用排空后注入，保证 assistant(tool_calls) 与 tool 消息严格配对
            if self.guidance is not None:
                await self._inject_guidance(session)

            # ---------- Model Call（原生 function calling） ----------
            messages = self.context.prepare(session)
            response = await llm.complete(messages, tools=tools or None)
            self._account(session, response.usage.input_tokens, response.usage.output_tokens, response.cost_usd)
            session.steps += 1

            # ---------- Decision: Tool Calls（原生） ----------
            if response.tool_calls:
                session.add_message("assistant", response.content or "", tool_calls=response.tool_calls)
                batch: list[dict[str, Any]] = []
                for tc in response.tool_calls:
                    fn = tc.get("function") or {}
                    name = str(fn.get("name") or "")
                    if not name:
                        continue
                    batch.append(
                        {
                            "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                            "name": name,
                            "arguments": self._parse_arguments(fn.get("arguments")),
                        }
                    )
                if not batch:
                    session.add_message("user", "工具调用缺少函数名，请重新发起工具调用。")
                    self.sessions.save(session)
                    continue
                session.pending_calls = batch
                self.sessions.save(session)
                interrupted = await self._drain_pending_calls(session, ctx_factory)
                if interrupted is not None:
                    return interrupted
                continue

            # ---------- Decision: Final（content JSON） ----------
            decision = self._parse_final_decision(response.content)
            if decision is None:
                session.add_message(
                    "user",
                    "你的回复不是合法的 final 决策。若任务已完成，请直接输出 JSON（不要调用函数、不要输出解释性文字）："
                    '{"decision":"final","output":{<最终结构化输出>},"rationale":"<总结，一句话>"}',
                )
                self.sessions.save(session)
                continue

            if output_schema is not None:
                try:
                    validated = output_schema.model_validate(decision.output)
                    session.final_output = validated.model_dump()
                except ValidationError as exc:
                    feedback = "; ".join(
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:6]
                    )
                    session.add_message(
                        "user",
                        f"你的 final 输出不符合要求的结构：{feedback}\n"
                        f"请修正后重新输出 final（JSON Schema: "
                        f"{json.dumps(output_schema.model_json_schema(), ensure_ascii=False)[:1500]}）",
                    )
                    self.sessions.save(session)
                    continue
            else:
                session.final_output = decision.output or {}
            session.status = "finished"
            self.sessions.save(session)
            return AgentRunResult(
                status="finished", final_output=session.final_output, session_id=session.session_id
            )

    # =====================================================

    async def _drain_pending_calls(
        self, session: RuntimeSession, ctx_factory: ContextFactory
    ) -> Optional[AgentRunResult]:
        """执行待办工具调用批次；遇人工审批中断 → 返回 awaiting_approval（剩余保留，恢复后继续）。

        批次内全部执行完（即使个别失败）以保持 tool_calls 与 tool 消息严格配对。
        """
        while session.pending_calls:
            item = session.pending_calls[0]
            call = ToolCall(
                id=str(item.get("id") or uuid.uuid4().hex[:12]),
                name=str(item.get("name") or ""),
                arguments=dict(item.get("arguments") or {}),
            )
            try:
                result = await self.executor.execute(call, ctx_factory(session))
            except ApprovalRequired:
                session.status = "awaiting_approval"
                self.sessions.save(session)
                return AgentRunResult(status="awaiting_approval", session_id=session.session_id)
            self._append_tool_result(session, call.name, result, tool_call_id=call.id)
            if not result.ok:
                session.tool_failures += 1
            session.pending_calls.pop(0)
            self.sessions.save(session)
        return None

    async def _inject_guidance(self, session: RuntimeSession) -> None:
        """领取并注入用户补充要求（追加需求）：追加 user 消息，Agent 下一步即可感知。"""
        try:
            items = await self.guidance.drain(session.run_id)
        except Exception:  # noqa: BLE001 —— 领取失败不影响主流程
            logger.warning("guidance 领取失败 run=%s", session.run_id, exc_info=True)
            return
        if not items:
            return
        for item in items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            session.add_message(
                "user",
                f"[用户补充要求] {text}\n"
                "请在保持原任务目标与验收标准不变的前提下，将这些补充要求纳入你的实现；"
                "若补充要求与原任务冲突，以补充要求为准。",
            )
            await self.tracer.emit(
                session.run_id,
                EventType.GUIDANCE_APPLIED,
                f"用户补充要求已注入 Agent 上下文：{text[:140]}",
                agent="human",
            )
        self.sessions.save(session)

    def _tool_specs_for(self, agent: str) -> list[dict[str, Any]]:
        """按 Agent Capability Profile 生成 OpenAI 兼容工具定义（tools 参数）。"""
        if self.registry is None:
            return []
        profile = self.permissions.get_profile(agent)
        specs: list[dict[str, Any]] = []
        for defn in self.registry.defs_for(list(profile.tools)):
            allowed, _ = self.permissions.check(agent, defn.name)
            if not allowed:
                continue
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": defn.name,
                        "description": defn.description,
                        "parameters": defn.input_schema or {"type": "object", "properties": {}},
                    },
                }
            )
        return specs

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any]:
        """工具调用参数：原生 arguments 为 JSON 字符串（兼容已是 dict 的场景）。"""
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_final_decision(content: str) -> Optional[AgentDecision]:
        """解析 final 决策：标准 {"decision":"final","output":{...}}；容忍直接输出产物 JSON。"""
        data = extract_json(content)
        if not isinstance(data, dict) or not data:
            return None
        if data.get("decision") == "final" and isinstance(data.get("output"), dict):
            try:
                return AgentDecision.model_validate(data)
            except ValidationError:
                return None
        # 容忍模型直接输出产物（无 decision 包裹）
        if "decision" not in data and isinstance(data, dict):
            return AgentDecision(decision="final", output=data, rationale="(直接输出产物)")
        return None

    def _stop_reason(
        self,
        session: RuntimeSession,
        max_steps: int,
        max_tokens: int,
        max_cost: float,
        max_wall: float,
        max_failures: int,
    ) -> str:
        if session.steps >= max_steps:
            return f"达到 max_steps={max_steps} 停止条件"
        if session.input_tokens + session.output_tokens >= max_tokens:
            return f"达到 max_tokens={max_tokens} 停止条件"
        if session.cost_usd >= max_cost:
            return f"达到 max_cost={max_cost} USD 停止条件"
        if session.wall_time() >= max_wall:
            return f"达到 timeout={max_wall}s 停止条件"
        if session.tool_failures >= max_failures:
            return f"达到 max_tool_failures={max_failures} 停止条件"
        return ""

    def _append_tool_result(self, session: RuntimeSession, tool_name: str, result: Any, tool_call_id: str = "") -> None:
        observation = self.observation.adapt(tool_name, result)
        session.add_message(
            "tool",
            json.dumps(observation, ensure_ascii=False),
            name=tool_name,
            tool_call_id=tool_call_id or f"call_{uuid.uuid4().hex[:12]}",
        )

    def _account(self, session: RuntimeSession, input_tokens: int, output_tokens: int, cost: float) -> None:
        session.input_tokens += input_tokens
        session.output_tokens += output_tokens
        session.cost_usd = round(session.cost_usd + cost, 6)

    async def _finish(
        self, agent_run_id: Optional[int], session: RuntimeSession, result: AgentRunResult, agent: str
    ) -> AgentRunResult:
        await self.tracer.finish_agent_run(
            agent_run_id,
            status=result.status,
            input_tokens=session.input_tokens,
            output_tokens=session.output_tokens,
            cost_usd=session.cost_usd,
            steps=session.steps,
            tool_calls=len(session.recent_tool_calls(1000)),
            error=result.error,
        )
        message = f"{agent} finished"
        if result.stopped_reason:
            message = f"{agent} stopped: {result.stopped_reason}"
        elif result.error:
            message = f"{agent} failed: {result.error[:200]}"
        await self.tracer.emit(session.run_id, EventType.AGENT_FINISHED, message, agent=agent)
        return result

    async def _fail(
        self, agent_run_id: Optional[int], session: RuntimeSession, agent: str, status: str, error: str
    ) -> AgentRunResult:
        session.status = "failed"
        session.error = error
        self.sessions.save(session)
        result = AgentRunResult(status="failed", error=error, session_id=session.session_id)
        return await self._finish(agent_run_id, session, result, agent)
