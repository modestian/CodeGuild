"""Reviewer Agent：代码审查（FR-REV-01~07）。

验证"实现是否正确"（与 Test Agent 的"能否运行"分离）：
验收标准核对 / 架构一致性 / 缺陷检查 / 安全检查 / 复杂度与影响面 / 补充测试建议。
输出：approved + issues（severity / file / line / problem / suggestion）。
"""
from __future__ import annotations

import json

from app.agents.base import agent_prompt, ctx_factory_for, workspace_of
from app.harness.session import RuntimeSession
from app.schemas.artifacts import ReviewReport
from app.schemas.events import EventType
from app.services.app_context import AppContext
from app.storage import repositories as repo

MAX_DIFF_CHARS = 50_000


def _brief(state: dict, diff: str, diff_stat: str) -> str:
    requirements = state.get("requirements") or {}
    acs = requirements.get("acceptance_criteria") or []
    ac_lines = "\n".join(
        f"- {a.get('id', '')} {a.get('description', '')}" if isinstance(a, dict) else f"- {a}"
        for a in acs[:20]
    ) or "- (无)"

    architecture = state.get("architecture") or {}
    arch_summary = str(architecture.get("design_overview") or architecture.get("summary") or "")[:1200]
    tasks = state.get("task_dag") or []
    task_lines = "\n".join(
        f"- {t.get('id')} [{t.get('status')}] {t.get('title')}" for t in tasks[:30] if isinstance(t, dict)
    ) or "- (无)"

    test_results = state.get("test_results") or {}
    test_line = json.dumps(
        {
            "passed": test_results.get("passed"),
            "summary": test_results.get("summary"),
        },
        ensure_ascii=False,
    )

    return (
        f"## 验收标准（Acceptance Criteria）\n{ac_lines}\n\n"
        f"## 架构设计摘要\n{arch_summary}\n\n"
        f"## 任务完成情况\n{task_lines}\n\n"
        f"## 测试结果（供参考）\n{test_line}\n\n"
        f"## 代码变更统计\n{diff_stat}\n\n"
        f"## 代码差异（Diff）\n```diff\n{diff[:MAX_DIFF_CHARS]}\n```\n\n"
        "## 要求\n"
        "1) 对照验收标准与架构设计检查实现正确性\n"
        "2) 必要时用 read_file / search_code 查看完整文件上下文\n"
        "3) 检查潜在 Bug、安全问题、不必要复杂度、对现有模块的影响、是否需要补充测试\n"
        "4) 输出 final（ReviewReport）：approved / issues / criteria_coverage\n"
    )


async def run_reviewer(app: AppContext, state: dict) -> dict:
    run_id = state["run_id"]
    workspace = workspace_of(state)
    await app.tracer.emit(run_id, EventType.REVIEW_STARTED, "Reviewer started.", agent="reviewer")

    try:
        diff_stat = await app.workspaces.full_diff(workspace, stat_only=True)
        diff = await app.workspaces.full_diff(workspace, max_chars=MAX_DIFF_CHARS)
    except Exception as exc:  # noqa: BLE001
        diff_stat, diff = "", f"(无法生成 diff: {exc})"

    session = app.sessions.load(run_id, f"{run_id}:reviewer:final") or RuntimeSession(
        session_id=f"{run_id}:reviewer:final", run_id=run_id, agent="reviewer"
    )
    result = await app.runtime.run(
        run_id=run_id,
        agent="reviewer",
        system_prompt=agent_prompt("reviewer"),
        task_brief=_brief(state, diff, diff_stat),
        ctx_factory=ctx_factory_for(app, state, "reviewer"),
        output_schema=ReviewReport,
        mode="agentic",
        session=session,
        task_id="final",
    )

    report: ReviewReport | None = None
    if result.status == "finished" and result.final_output:
        try:
            report = ReviewReport.model_validate(result.final_output)
        except Exception:  # noqa: BLE001
            report = None
    if report is None:
        report = ReviewReport(
            approved=False,
            summary=f"Reviewer 未能输出结构化结果: {(result.error or result.stopped_reason or '')[:200]}",
            issues=[],
        )

    report_dict = report.model_dump()
    artifact = app.save_artifact(run_id, "review_report", report_dict)
    async with app.database.session() as session_db:
        await repo.add_review(session_db, run_id, "", report.approved, report_dict)

    if report.approved:
        message = "Reviewer approved."
    else:
        message = f"Reviewer rejected: {len(report.issues)} issue(s)."
    await app.tracer.emit(run_id, EventType.REVIEW_RESULT, message, agent="reviewer", data=report_dict)

    return {
        "review_results": report_dict,
        "current_agent": "reviewer",
        "artifacts": {**(state.get("artifacts") or {}), "review_report": artifact},
    }
