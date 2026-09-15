"""Test Agent：自动化测试与结果分析（FR-TEST-01~06）。

独立于 Coding Agent；执行 Unit / Integration Test、Build、Lint、Static Analysis，
输出结构化结果 passed / summary / failures。
"""
from __future__ import annotations

from app.agents.base import agent_prompt, ctx_factory_for, workspace_of
from app.harness.session import RuntimeSession
from app.schemas.artifacts import TestFailure, TestReport, TestSummary
from app.schemas.events import EventType
from app.schemas.tool import ToolCall
from app.services.app_context import AppContext


def _brief(state: dict) -> str:
    tasks = state.get("task_dag") or []
    done = [t for t in tasks if isinstance(t, dict) and t.get("status") == "COMPLETED"]
    task_lines = "\n".join(f"- {t.get('id')}: {t.get('title')}" for t in done[:20]) or "- (无)"
    test_cmd = state.get("_test_command") or ""
    return (
        "## 已完成任务\n" + task_lines + "\n\n"
        "## 目标\n"
        "对当前工作区执行完整测试与检查：\n"
        "1) 先执行 run_test（项目测试命令）\n"
        "2) 如配置了 lint/build 命令，执行 run_linter / run_build\n"
        "3) 如失败，读取相关代码与失败信息，分析根因（你不修改代码）\n"
        "4) 输出 final 结构化测试报告（TestReport）\n"
    )


def report_from_observation(observation: dict, command: str) -> TestReport:
    """从 Observation Adapter 的结构化观察构造 TestReport。"""
    summary_raw = observation.get("summary") or {}
    summary = TestSummary(
        total=int(summary_raw.get("total", 0) or 0),
        passed=int(summary_raw.get("passed", 0) or 0),
        failed=int(summary_raw.get("failed", 0) or 0),
        errors=int(summary_raw.get("errors", 0) or 0),
        skipped=int(summary_raw.get("skipped", 0) or 0),
    )
    failures = []
    for item in (observation.get("failures") or [])[:20]:
        if isinstance(item, dict) and item.get("test"):
            failures.append(TestFailure(test=str(item["test"]), message=str(item.get("message", ""))[:500]))
    passed = bool(observation.get("passed")) if "passed" in observation else observation.get("status") == "success"
    return TestReport(
        passed=passed,
        summary=summary,
        failures=failures,
        commands=[command] if command else [],
        notes=str(observation.get("error_summary", ""))[:500],
    )


async def direct_test_run(app: AppContext, state: dict) -> TestReport:
    """确定性测试执行（兜底）：不经过 LLM，直接在沙箱运行测试命令并解析。"""
    session = RuntimeSession(
        session_id=f"{state['run_id']}:tester:direct", run_id=state["run_id"], agent="tester"
    )
    ctx = ctx_factory_for(app, state, "tester")(session)
    command = app.settings.test_command
    result = await app.executor.execute(ToolCall(name="run_test", arguments={}), ctx)
    observation = app.observation.adapt("run_test", result)
    report = report_from_observation(observation, command)
    if not result.ok and result.error:
        report.notes = f"{report.notes}\n{result.error[:400]}".strip()
    return report


async def run_tester(app: AppContext, state: dict) -> dict:
    run_id = state["run_id"]
    await app.tracer.emit(run_id, EventType.TEST_STARTED, "Test Agent started.", agent="tester")

    session = app.sessions.load(run_id, f"{run_id}:tester:integration") or RuntimeSession(
        session_id=f"{run_id}:tester:integration", run_id=run_id, agent="tester"
    )
    result = await app.runtime.run(
        run_id=run_id,
        agent="tester",
        system_prompt=agent_prompt("tester"),
        task_brief=_brief(state),
        ctx_factory=ctx_factory_for(app, state, "tester"),
        output_schema=TestReport,
        mode="agentic",
        session=session,
        task_id="integration",
    )

    report: TestReport | None = None
    if result.status == "finished" and result.final_output:
        try:
            report = TestReport.model_validate(result.final_output)
        except Exception:  # noqa: BLE001
            report = None

    # 保证至少执行过一次真实测试（FR-TEST-02/03）
    if report is None or not report.commands:
        report = await direct_test_run(app, state)
        report.notes = (report.notes + "\n（由确定性测试执行兜底）").strip()

    report_dict = report.model_dump()
    artifact = app.save_artifact(run_id, "test_report", report_dict)

    if report.passed:
        message = (
            f"{report.summary.passed} tests passed."
            if report.summary.total
            else "tests passed（无失败用例）."
        )
    else:
        failed = report.summary.failed + report.summary.errors
        message = f"{failed} tests failed." if failed else "tests failed."
    await app.tracer.emit(run_id, EventType.TEST_RESULT, message, agent="tester", data=report_dict)

    return {
        "test_results": report_dict,
        "current_agent": "tester",
        "artifacts": {**(state.get("artifacts") or {}), "test_report": artifact},
    }
