"""Supervisor：中央协调与调度决策（FR-SUP-01~09）。

- MVP（supervisor_mode=fixed）：基于 Shared State 的固定顺序调度
- V2（supervisor_mode=dynamic）：LLM 基于状态摘要动态路由（候选集约束 + 失败回退固定逻辑）

调度决策输出始终包含 next_agent 与 reason。
"""
from __future__ import annotations

from app.agents.base import agent_prompt, append_history, ctx_factory_for, workspace_of
from app.schemas.artifacts import SupervisorDecision
from app.schemas.events import EventType
from app.services.app_context import AppContext

# 允许的下一节点（Conditional Edge 路由目标）
ALLOWED_AGENTS = {"product", "architect", "development", "final_review", "human_approval", "commit", "end"}


def fixed_decision(state: dict, max_code_retry: int) -> SupervisorDecision:
    """MVP 固定顺序调度：依据 Shared State 判断阶段（FR-LG-02 主流程）。"""
    status = state.get("run_status")
    if status in {"completed", "rejected", "failed", "cancelled"}:
        return SupervisorDecision(next_agent="end", reason=f"run_status={status}，流程结束")

    if state.get("needs_human"):
        reason = state.get("fail_reason") or "需要人工介入"
        return SupervisorDecision(next_agent="human_approval", reason=f"触发人工介入: {reason}")

    if not state.get("requirements"):
        return SupervisorDecision(next_agent="product", reason="requirements not ready: 先进行需求分析")
    if not state.get("architecture"):
        return SupervisorDecision(next_agent="architect", reason="architecture not ready: 进行技术设计与任务拆分")

    if not state.get("dev_cycle_done"):
        return SupervisorDecision(next_agent="development", reason="development tasks pending: 进入开发闭环")

    if not state.get("final_report"):
        return SupervisorDecision(next_agent="final_review", reason="development done: 执行最终质量门")

    final_report = state.get("final_report") or {}
    approval = state.get("approval") or {}
    if not approval:
        if final_report.get("ready_for_approval"):
            return SupervisorDecision(next_agent="human_approval", reason="变更已就绪，等待人工审批")
        retries = state.get("retries") or {}
        if retries.get("code", 0) < max_code_retry:
            return SupervisorDecision(next_agent="development", reason="final review 未就绪，回到开发修复")
        return SupervisorDecision(
            next_agent="human_approval",
            reason=f"修复轮次已达上限（{retries.get('code', 0)}/{max_code_retry}），转人工介入",
        )

    decision = str(approval.get("decision", "")).lower()
    if decision in {"approve", "yes", "approved"}:
        if not state.get("commits"):
            return SupervisorDecision(next_agent="commit", reason="人工审批通过，执行 Git Commit")
        return SupervisorDecision(next_agent="end", reason="已完成提交，流程结束")
    return SupervisorDecision(next_agent="end", reason="人工审批拒绝，流程终止")


def _state_summary(state: dict) -> str:
    tasks = list(state.get("task_dag") or [])
    statuses: dict[str, int] = {}
    for t in tasks:
        key = t.get("status", "PENDING") if isinstance(t, dict) else str(t)
        statuses[key] = statuses.get(key, 0) + 1
    final_report = state.get("final_report") or {}
    test = state.get("test_results") or {}
    review = state.get("review_results") or {}
    summary = {
        "requirements_ready": bool(state.get("requirements")),
        "architecture_ready": bool(state.get("architecture")),
        "task_status": statuses,
        "dev_cycle_done": bool(state.get("dev_cycle_done")),
        "tests_passed": test.get("passed"),
        "review_approved": review.get("approved"),
        "final_ready_for_approval": final_report.get("ready_for_approval"),
        "approval": (state.get("approval") or {}).get("decision"),
        "commits": len(state.get("commits") or []),
        "needs_human": bool(state.get("needs_human")),
        "retries": state.get("retries") or {},
    }
    import json

    return json.dumps(summary, ensure_ascii=False)


async def _dynamic_decision(app: AppContext, state: dict) -> SupervisorDecision:
    """V2 动态路由：LLM 决策（本 MVP 已提供实现，通过 SUPERVISOR_MODE=dynamic 启用）。"""
    fixed = fixed_decision(state, app.settings.max_code_retry)
    task_brief = (
        f"## 当前 Shared State 摘要\n{_state_summary(state)}\n\n"
        f"## 候选 next_agent（只能从中选择）\n"
        "- product: 需求分析未完成\n"
        "- architect: 架构/任务未完成\n"
        "- development: 开发闭环未完成或需要修复\n"
        "- final_review: 开发完成，执行最终质量门\n"
        "- human_approval: 需要人工审批或人工介入\n"
        "- end: 流程结束\n\n"
        f"## 参考决策（固定规则）\nnext_agent={fixed.next_agent}, reason={fixed.reason}\n\n"
        "请基于状态选择最合理的 next_agent 并给出 reason。"
    )
    try:
        result = await app.runtime.run(
            run_id=state["run_id"],
            agent="supervisor",
            system_prompt=agent_prompt("supervisor"),
            task_brief=task_brief,
            ctx_factory=ctx_factory_for(app, state, "supervisor"),
            output_schema=SupervisorDecision,
            mode="single",
        )
        if result.status == "finished" and result.final_output:
            decision = SupervisorDecision.model_validate(result.final_output)
            if decision.next_agent in ALLOWED_AGENTS and decision.reason:
                return decision
    except Exception:  # noqa: BLE001 —— 动态路由失败回退固定逻辑
        pass
    return fixed


async def run_supervisor(app: AppContext, state: dict) -> dict:
    run_id = state["run_id"]
    await app.tracer.emit(run_id, EventType.SUPERVISOR_ANALYZING, "Supervisor analyzing project...", agent="supervisor")

    if app.settings.supervisor_mode == "dynamic":
        decision = await _dynamic_decision(app, state)
    else:
        decision = fixed_decision(state, app.settings.max_code_retry)

    iteration = int(state.get("iteration") or 0) + 1
    await app.tracer.emit(
        run_id,
        EventType.SUPERVISOR_DECISION,
        f"Supervisor → {decision.next_agent}: {decision.reason}",
        agent="supervisor",
        data={"next_agent": decision.next_agent, "reason": decision.reason},
    )
    return {
        "route": decision.next_agent,
        "supervisor_reason": decision.reason,
        "current_agent": "supervisor",
        "iteration": iteration,
        "supervisor_history": append_history(
            state, {"iteration": iteration, "next_agent": decision.next_agent, "reason": decision.reason}
        ),
    }
