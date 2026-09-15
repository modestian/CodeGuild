"""Product Agent：需求结构化（FR-PROD-01~06）。

输入：用户需求、现有项目背景、项目约束
输出：结构化 JSON（features / user_stories / acceptance_criteria /
non_functional_requirements / open_questions）
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
from app.memory.project import ProjectMemory
from app.schemas.artifacts import Requirements
from app.schemas.events import EventType
from app.services.app_context import AppContext


async def run_product(app: AppContext, state: dict) -> dict:
    run_id = state["run_id"]
    workspace = workspace_of(state)

    overview = build_repo_overview(workspace)
    memory = ProjectMemory()
    conventions = memory.coding_conventions(workspace, max_chars=1200)

    task_brief = (
        f"## 用户需求\n{state['user_request']}\n\n"
        f"## 现有项目背景\n{overview}\n\n"
        "## 项目约束\n"
        "- 目标：在现有代码仓库中实现上述需求，最终产出可提交的代码变更\n"
        "- 请同时注意：现有代码风格与结构必须被尊重\n"
        "请输出结构化产品需求（JSON）。"
    )

    result = await app.runtime.run(
        run_id=run_id,
        agent="product",
        system_prompt=agent_prompt("product"),
        task_brief=task_brief,
        ctx_factory=ctx_factory_for(app, state, "product"),
        output_schema=Requirements,
        mode="single",
        memory_excerpt=conventions,
    )

    if result.status != "finished" or not result.final_output:
        detail = result.error or result.stopped_reason or "unknown"
        await app.tracer.emit(
            run_id, EventType.RUN_FAILED, f"Product Agent 失败: {detail[:200]}", agent="product"
        )
        return {
            "current_agent": "product",
            "run_status": "failed",
            "fail_reason": f"需求分析失败: {detail[:300]}",
            "errors": merged_errors(state, make_error("product", detail)),
        }

    requirements = result.final_output
    artifact = app.save_artifact(run_id, "requirements", requirements)
    open_questions = requirements.get("open_questions") or []
    features = requirements.get("features") or []
    acs = requirements.get("acceptance_criteria") or []
    message = f"Product Agent: {len(features)} features, {len(acs)} acceptance criteria"
    if open_questions:
        message += f", {len(open_questions)} open questions"
    await app.tracer.emit(run_id, EventType.REQUIREMENTS_READY, message, agent="product")
    if open_questions:
        questions = "; ".join(
            str(q.get("question", q))[:120] for q in open_questions[:5]
        )
        await app.tracer.emit(
            run_id,
            EventType.LOG,
            f"待澄清问题（按默认假设继续）: {questions}",
            agent="product",
        )

    return {
        "requirements": requirements,
        "open_questions": open_questions,
        "current_agent": "product",
        "artifacts": {**(state.get("artifacts") or {}), "requirements": artifact},
        "run_status": "running",
    }
