"""Research Agent：外部知识研究（FR-RES-01~04，V2 完整接入）。

MVP 提供结构化框架：当 Coding / Architect 缺少外部知识时，经 Supervisor 路由至
Research Agent，由其返回 Structured Research Result。外部资料检索（官方文档 / GitHub /
API Reference）通过 MCP 与 web 工具在 V2 接入（MVP 不做 MCP）。
"""
from __future__ import annotations

from app.agents.base import agent_prompt, ctx_factory_for
from app.memory.long_term import LongTermMemory
from app.schemas.artifacts import ResearchResult
from app.services.app_context import AppContext


async def run_research(app: AppContext, state: dict, question: str) -> dict:
    run_id = state["run_id"]
    memory = LongTermMemory(app.settings.artifacts_dir, state.get("project_id", "unknown"))
    known = memory.excerpt(max_chars=800)

    task_brief = (
        f"## 研究问题\n{question}\n\n"
        f"## 已有长期记忆（可能相关）\n{known or '(无)'}\n\n"
        "## 约束\n"
        "- 当前环境未接入外部检索工具，若无法确认，请降低 confidence 并在 answer 中说明\n"
        "- 输出 final（ResearchResult）"
    )
    result = await app.runtime.run(
        run_id=run_id,
        agent="researcher",
        system_prompt=agent_prompt("researcher"),
        task_brief=task_brief,
        ctx_factory=ctx_factory_for(app, state, "researcher"),
        output_schema=ResearchResult,
        mode="single",
    )
    if result.status == "finished" and result.final_output:
        return {"research_results": result.final_output}
    return {
        "research_results": ResearchResult(
            question=question,
            findings=[],
            sources=[],
            confidence="low",
            answer=f"研究未能完成: {(result.error or result.stopped_reason or '')[:200]}",
        ).model_dump()
    }
