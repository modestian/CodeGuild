"""Analyst Agent 与 Intent Router（只读问答 + 请求意图分类）。

- classify_intent：判断请求属于 query（只读回答）还是 develop（开发闭环）
- run_analyst：只读探索仓库并回答（介绍 / 解释类问题），不修改任何文件
"""
from __future__ import annotations

from app.agents.base import (
    agent_prompt,
    build_repo_overview,
    ctx_factory_for,
    make_error,
    merged_errors,
    workspace_of,
)
from app.schemas.artifacts import AnswerResult, IntentDecision
from app.schemas.events import EventType
from app.services.app_context import AppContext


async def classify_intent(app: AppContext, state: dict) -> dict:
    """请求意图分类：query | develop。

    - request_mode 显式指定 query/develop 时跳过 LLM 分类
    - LLM 分类失败/异常时保守回退 develop（开发闭环），避免漏做需求
    """
    run_id = state["run_id"]
    mode = str(state.get("request_mode") or "auto").lower()

    if mode in {"query", "develop"}:
        intent = mode
        reason = f"用户显式指定运行模式：{mode}"
    else:
        overview = build_repo_overview(workspace_of(state), max_chars=1500)
        task_brief = (
            f"## 用户请求\n{state.get('user_request', '')}\n\n"
            f"## 仓库概览\n{overview}\n\n"
            "请判断该请求意图（query | develop），并严格按输出 JSON 要求作答。"
        )
        try:
            result = await app.runtime.run(
                run_id=run_id,
                agent="intent_router",
                system_prompt=agent_prompt("intent_router"),
                task_brief=task_brief,
                ctx_factory=ctx_factory_for(app, state, "intent_router"),
                output_schema=IntentDecision,
                mode="single",
            )
            if result.status == "finished" and result.final_output:
                decision = IntentDecision.model_validate(result.final_output)
                intent = "query" if decision.intent == "query" else "develop"
                reason = decision.reason or "LLM 分类结果"
            else:
                detail = result.error or result.stopped_reason or "unknown"
                intent, reason = "develop", f"分类失败（{detail[:100]}），回退开发闭环"
        except Exception as exc:  # noqa: BLE001
            intent, reason = "develop", f"分类异常（{str(exc)[:100]}），回退开发闭环"

    await app.tracer.emit(
        run_id,
        EventType.INTENT_DECIDED,
        f"意图判定：{'只读问答' if intent == 'query' else '开发闭环'}（{reason}）",
        agent="intent_router",
        data={"intent": intent, "reason": reason},
    )
    return {"request_intent": intent, "current_agent": "intent_router"}


async def run_analyst(app: AppContext, state: dict) -> dict:
    """只读问答：agentic 探索仓库后给出回答（不写任何文件）。"""
    run_id = state["run_id"]
    overview = build_repo_overview(workspace_of(state), max_chars=1800)
    task_brief = (
        f"## 用户问题\n{state.get('user_request', '')}\n\n"
        f"## 仓库概览（需要更多细节请用只读工具自行探索）\n{overview}\n\n"
        "请给出简洁、准确的中文回答，并严格按输出 JSON 要求作答。"
    )

    result = await app.runtime.run(
        run_id=run_id,
        agent="analyst",
        system_prompt=agent_prompt("analyst"),
        task_brief=task_brief,
        ctx_factory=ctx_factory_for(app, state, "analyst"),
        output_schema=AnswerResult,
        mode="agentic",
        task_id="answer",
    )

    if result.status != "finished" or not result.final_output:
        detail = result.error or result.stopped_reason or "unknown"
        await app.tracer.emit(
            run_id, EventType.RUN_FAILED, f"Analyst 回答失败：{detail[:200]}", agent="analyst"
        )
        return {
            "current_agent": "analyst",
            "run_status": "failed",
            "fail_reason": f"只读问答失败：{detail[:300]}",
            "errors": merged_errors(state, make_error("analyst", detail)),
        }

    answer = result.final_output
    artifact = app.save_artifact(run_id, "answer", answer)
    await app.tracer.emit(
        run_id,
        EventType.ANSWER_READY,
        "只读问答完成",
        agent="analyst",
        data={"answer": answer},
    )
    return {
        "answer": answer,
        "current_agent": "analyst",
        "run_status": "completed",
        "artifacts": {**(state.get("artifacts") or {}), "answer": artifact},
    }
