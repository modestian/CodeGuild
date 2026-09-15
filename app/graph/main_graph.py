"""Main Graph（FR-LG-02/03、FR-HITL-01~05）。

START → Load Project → Supervisor → Product → Architect → Development SubGraph →
Final Review → Human Approval →（approve: Git Commit）→ END

Supervisor 通过 Conditional Edge 动态跳转（V2 dynamic 模式基于 Shared State 路由）。
"""
from __future__ import annotations

import time
import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.analyst import classify_intent as run_intent_router
from app.agents.analyst import run_analyst
from app.agents.architect import run_architect
from app.agents.base import dump_tasks, make_error, merged_errors, tasks_of, workspace_of
from app.agents.product import run_product
from app.agents.supervisor import run_supervisor
from app.graph.development_graph import build_development_graph
from app.graph.routing import route_after_intent, route_after_supervisor
from app.graph.safe_point import pause_safe_point
from app.schemas.artifacts import FinalReport
from app.schemas.events import EventType
from app.schemas.state import DevState, TaskStatus
from app.services.app_context import AppContext
from app.storage import repositories as repo


def _brief_request(text: str, n: int = 72) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def build_main_graph(app: AppContext, checkpointer=None):
    """编译 Main Graph（需要 checkpointer 以支持 interrupt 与恢复）。"""
    development_graph = build_development_graph(app)

    # =====================================================
    # Load Project
    # =====================================================

    async def load_project(state: dict) -> dict:
        await app.tracer.emit(
            state["run_id"],
            EventType.RUN_STARTED,
            f"Run started: {_brief_request(state.get('user_request', ''))}",
            agent="system",
        )
        await app.tracer.record_checkpoint(state["run_id"], "load_project", 0, "system")
        return {"run_status": "running"}

    # =====================================================
    # Intent Router（query 只读问答 | develop 开发闭环）
    # =====================================================

    async def classify_intent(state: dict) -> dict:
        try:
            return await run_intent_router(app, state)
        except Exception as exc:  # noqa: BLE001 —— 保守回退开发闭环
            return {"request_intent": "develop", "current_agent": "intent_router"}

    # =====================================================
    # Answer（只读问答，query 模式直接回答后结束）
    # =====================================================

    async def answer(state: dict) -> dict:
        try:
            return await run_analyst(app, state)
        except Exception as exc:  # noqa: BLE001
            return {
                "current_agent": "analyst",
                "run_status": "failed",
                "fail_reason": f"Analyst Agent 异常: {exc}",
                "errors": merged_errors(state, make_error("analyst", str(exc))),
            }

    # =====================================================
    # Supervisor
    # =====================================================

    async def supervisor(state: dict) -> dict:
        # ---- 人工打断安全点（HITL：pause/resume）----
        await pause_safe_point(app, state, "调度前")

        updates = await run_supervisor(app, state)
        await app.tracer.record_checkpoint(
            state["run_id"], "supervisor", int(updates.get("iteration", 0)), "supervisor"
        )
        return updates

    # =====================================================
    # Agents
    # =====================================================

    async def product(state: dict) -> dict:
        try:
            return await run_product(app, state)
        except Exception as exc:  # noqa: BLE001
            return {
                "current_agent": "product",
                "run_status": "failed",
                "fail_reason": f"Product Agent 异常: {exc}",
                "errors": merged_errors(state, make_error("product", str(exc))),
            }

    async def architect(state: dict) -> dict:
        try:
            return await run_architect(app, state)
        except Exception as exc:  # noqa: BLE001
            return {
                "current_agent": "architect",
                "run_status": "failed",
                "fail_reason": f"Architect Agent 异常: {exc}",
                "errors": merged_errors(state, make_error("architect", str(exc))),
            }

    # =====================================================
    # Final Review（最终质量门）
    # =====================================================

    async def final_review(state: dict) -> dict:
        tasks = tasks_of(state)
        test_results = state.get("test_results") or {}
        review_results = state.get("review_results") or {}
        changed = state.get("changed_files") or []
        total = len(tasks)
        completed = len([t for t in tasks if t.status == TaskStatus.COMPLETED])

        blockers: list[str] = []
        if completed < total:
            blockers.append(f"未完成任务: {total - completed}/{total}")
        if not test_results.get("passed"):
            blockers.append("测试未通过")
        if not review_results.get("approved"):
            blockers.append("Review 未通过")
        if not changed:
            blockers.append("无代码变更")

        ready = not blockers
        report = FinalReport(
            ready_for_approval=ready,
            tasks_total=total,
            tasks_completed=completed,
            tests_passed=bool(test_results.get("passed")),
            review_approved=bool(review_results.get("approved")),
            changed_files=[c.get("path", "") for c in changed if isinstance(c, dict)],
            summary=(
                f"{completed}/{total} tasks completed; "
                f"tests {'passed' if test_results.get('passed') else 'failed'}; "
                f"review {'approved' if review_results.get('approved') else 'rejected'}; "
                f"{len(changed)} file(s) changed."
            ),
            blockers=blockers,
        )
        artifact = app.save_artifact(state["run_id"], "final_report", report.model_dump())
        await app.tracer.emit(
            state["run_id"],
            EventType.DIFF_READY,
            (
                f"Final review: ready for approval（{len(changed)} files changed）"
                if ready
                else f"Final review: not ready — {'; '.join(blockers)}"
            ),
            agent="system",
            data=report.model_dump(),
        )

        updates: dict = {
            "final_report": report.model_dump(),
            "artifacts": {**(state.get("artifacts") or {}), "final_report": artifact},
            "current_agent": "final_review",
        }
        if not ready:
            retries = dict(state.get("retries") or {"code": 0, "test": 0, "review": 0, "plan": 0})
            retries["code"] = retries.get("code", 0) + 1
            updates["retries"] = retries
            if retries["code"] >= app.settings.max_code_retry:
                updates["needs_human"] = True
                updates["fail_reason"] = f"Final Review 未通过且修复轮次达到上限: {'; '.join(blockers)}"
            else:
                # 回到开发闭环：重置失败/阻塞任务，清除 final_report 以便再次评审
                failed = [t for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)]
                for t in failed:
                    t.status = TaskStatus.PENDING
                    t.attempts = 0
                updates["task_dag"] = dump_tasks(tasks)
                updates["final_report"] = {}
                updates["dev_cycle_done"] = False
                async with app.database.session() as session_db:
                    await repo.sync_tasks(session_db, state["run_id"], tasks)
        return updates

    # =====================================================
    # Human Approval（interrupt）
    # =====================================================

    async def human_approval(state: dict) -> dict:
        report = state.get("final_report") or {}
        needs_human = bool(state.get("needs_human"))
        test_results = state.get("test_results") or {}
        review_results = state.get("review_results") or {}
        retries = state.get("retries") or {}
        payload = {
            "type": "approval_required",
            "run_id": state["run_id"],
            "approval_id": uuid.uuid4().hex,  # 每次挂起唯一，供前端区分多次请求
            "reason": state.get("fail_reason")
            if needs_human
            else "所有任务已完成并通过测试与审查，请审批提交",
            "needs_human": needs_human,
            "summary": report.get("summary", ""),
            "tasks_total": report.get("tasks_total", 0),
            "tasks_completed": report.get("tasks_completed", 0),
            "tests_passed": report.get("tests_passed", False),
            "review_approved": report.get("review_approved", False),
            "blockers": (report.get("blockers") or [])[:8],
            # 超限诊断信息（供用户决定继续修复 / 强制通过 / 拒绝）
            "retries": retries,
            "max_code_retry": app.settings.max_code_retry,
            "review_issues": [
                {
                    "severity": str(i.get("severity", "")),
                    "file": str(i.get("file", "")),
                    "problem": str(i.get("problem", ""))[:200],
                    "suggestion": str(i.get("suggestion", ""))[:200],
                }
                for i in (review_results.get("issues") or [])[:6]
                if isinstance(i, dict)
            ],
            "test_failures": [
                {
                    "test": str(f.get("test", "")),
                    "message": str(f.get("message", ""))[:200],
                    "file": str(f.get("file", "")),
                }
                for f in (test_results.get("failures") or [])[:5]
                if isinstance(f, dict)
            ],
            "changed_files": [c.get("path", "") for c in (state.get("changed_files") or []) if isinstance(c, dict)][:50],
            "options": ["continue", "approve", "reject"] if needs_human else ["approve", "reject"],
        }

        decision = interrupt(payload)
        if isinstance(decision, str):
            decision = {"decision": decision}
        decision = decision or {}
        action = str(decision.get("decision", "")).lower()
        note = str(decision.get("note", ""))
        by = str(decision.get("by", "user"))

        # 审批留痕（FR-HITL-06）
        if action != "continue":
            await app.approvals.record_decision(
                state["run_id"],
                "git_commit",
                "approve" if action in {"approve", "yes", "approved"} else "reject",
                note,
                by,
            )

        if action == "continue":
            await app.tracer.emit(
                state["run_id"], EventType.APPROVAL_RECEIVED, "Human chose to continue repairing.", agent="human"
            )
            # 额外需求（note）注入 guidance：下一轮修复将自动携带
            if note.strip():
                await app.guidance.add(state["run_id"], note.strip(), source="user")
                await app.tracer.emit(
                    state["run_id"],
                    EventType.LOG,
                    f"额外需求已注入修复上下文：{note.strip()[:160]}",
                    agent="human",
                )
            tasks = tasks_of(state)
            for t in tasks:
                if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                    t.status = TaskStatus.PENDING
                    t.attempts = 0
            async with app.database.session() as session_db:
                await repo.sync_tasks(session_db, state["run_id"], tasks)
            return {
                "needs_human": False,
                "fail_reason": "",
                "dev_cycle_done": False,
                "final_report": {},
                "retries": {"code": 0, "test": 0, "review": 0, "plan": 0},
                "task_dag": dump_tasks(tasks),
                "approval": {},
            }

        approved = action in {"approve", "yes", "approved"}
        # 审批意见（note）注入 guidance：覆盖剩余执行（如"提交后请补充文档"）
        if note.strip() and approved:
            await app.guidance.add(state["run_id"], note.strip(), source="user")
        await app.tracer.emit(
            state["run_id"],
            EventType.APPROVAL_RECEIVED,
            f"Human {'approved' if approved else 'rejected'} the change" + (f": {note[:120]}" if note else "."),
            agent="human",
        )
        updates: dict = {
            "approval": {"decision": "approve" if approved else "reject", "note": note, "by": by, "ts": time.time()}
        }
        if approved:
            updates["needs_human"] = False
        else:
            updates["run_status"] = "rejected"
        return updates

    # =====================================================
    # Git Commit（审批通过后执行；MVP 不做自动 Push）
    # =====================================================

    async def commit(state: dict) -> dict:
        workspace = workspace_of(state)
        architecture = state.get("architecture") or {}
        subject = _brief_request(
            str(architecture.get("summary") or architecture.get("design_overview") or state.get("user_request", "")),
            68,
        )
        tasks = tasks_of(state)
        done = [t.id for t in tasks if t.status == TaskStatus.COMPLETED]
        message = (
            f"feat: {subject}\n\n"
            f"Multi-Agent Copilot run {state['run_id'][:8]}\n"
            f"Tasks: {', '.join(done) or '(none)'}\n"
        )
        try:
            result = await app.workspaces.commit(workspace, message)
            await app.tracer.emit(
                state["run_id"],
                EventType.COMMIT_DONE,
                f"Committed {result.get('sha')} on {state.get('branch', '')}",
                agent="commit",
                data=result,
            )
            return {
                "commits": [
                    {"sha": result.get("sha"), "branch": state.get("branch", ""), "message": subject}
                ],
                "run_status": "completed",
                "current_agent": "commit",
            }
        except Exception as exc:  # noqa: BLE001
            await app.tracer.emit(
                state["run_id"], EventType.ERROR, f"Commit 失败: {str(exc)[:200]}", agent="commit"
            )
            return {
                "run_status": "failed",
                "fail_reason": f"Git Commit 失败: {str(exc)[:300]}",
                "errors": merged_errors(state, make_error("commit", str(exc))),
            }

    # =====================================================
    # 图结构
    # =====================================================

    graph = StateGraph(DevState)
    graph.add_node("load_project", load_project)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("answer", answer)
    graph.add_node("supervisor", supervisor)
    graph.add_node("product", product)
    graph.add_node("architect", architect)
    graph.add_node("development", development_graph)
    graph.add_node("final_review", final_review)
    graph.add_node("human_approval", human_approval)
    graph.add_node("commit", commit)

    graph.add_edge(START, "load_project")
    graph.add_edge("load_project", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_after_intent,
        {"answer": "answer", "supervisor": "supervisor"},
    )
    graph.add_edge("answer", END)
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "product": "product",
            "architect": "architect",
            "development": "development",
            "final_review": "final_review",
            "human_approval": "human_approval",
            "commit": "commit",
            "end": END,
        },
    )
    for node in ("product", "architect", "development", "final_review", "human_approval", "commit"):
        graph.add_edge(node, "supervisor")

    return graph.compile(checkpointer=checkpointer)
