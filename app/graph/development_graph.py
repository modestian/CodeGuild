"""Development SubGraph（FR-LG-04、FR-FIX-01~04）。

Task Scheduler → Detect Ready Tasks → Coding Agents → Integration（V2）→ Testing →
（Failed: Repair / Passed: Review → Return）

- MVP 顺序执行就绪任务（并行 Coding Agents 为 V2，调度器已按 DAG 计算就绪集合）
- Test Loop：Coding → Testing → PASS? →（NO: Repair / YES: Review）
- Review Loop：Reviewer → Approved? →（NO: Fix / YES: Finish）
- 重试超限（MAX_CODE_RETRY / MAX_TEST_RETRY / MAX_REVIEW_RETRY）→ 转人工介入（needs_human）
"""
from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph

from app.agents.base import dump_tasks, make_error, merged_errors, tasks_of
from app.agents.reviewer import run_reviewer
from app.agents.tester import run_tester
from app.graph.coding_graph import build_coding_graph
from app.graph.routing import (
    DEV_ROUTES,
    route_after_finalize,
    route_after_repair,
    route_after_review,
    route_after_scheduler,
    route_after_testing,
)
from app.graph.safe_point import pause_safe_point
from app.schemas.events import EventType
from app.schemas.state import DevState, TaskRecord, TaskStatus, compute_ready_tasks, propagate_blocking, topological_order
from app.services.app_context import AppContext
from app.storage import repositories as repo


def _compose_feedback(state: dict, stage: str) -> str:
    if stage == "test":
        report = state.get("test_results") or {}
        lines = ["测试未通过，请修复相关代码："]
        summary = report.get("summary") or {}
        if summary:
            lines.append(f"summary: {json.dumps(summary, ensure_ascii=False)}")
        for item in (report.get("failures") or [])[:8]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('test')}: {str(item.get('message', ''))[:220]}")
        return "\n".join(lines)
    if stage == "review":
        report = state.get("review_results") or {}
        lines = ["Review 未通过，请按以下问题修复（不要重新实现业务逻辑）："]
        for item in (report.get("issues") or [])[:10]:
            if isinstance(item, dict):
                lines.append(
                    f"- [{item.get('severity')}] {item.get('file')}:{item.get('line')} "
                    f"{str(item.get('problem', ''))[:200]} → 建议: {str(item.get('suggestion', ''))[:200]}"
                )
        if not (report.get("issues") or []):
            lines.append(f"- {str(report.get('summary', ''))[:300]}")
        return "\n".join(lines)
    # code / validation
    validation = state.get("validation") or {}
    lines = ["验证未通过，请修复："]
    summary = validation.get("summary") or {}
    if summary:
        lines.append(f"summary: {json.dumps(summary, ensure_ascii=False)}")
    for item in (validation.get("failures") or [])[:8]:
        if isinstance(item, dict):
            lines.append(f"- {item.get('test')}: {str(item.get('message', ''))[:220]}")
    if validation.get("error"):
        lines.append(f"错误摘要: {str(validation['error'])[:400]}")
    return "\n".join(lines)


def build_development_graph(app: AppContext):
    """编译 Development SubGraph（含 Coding SubGraph 作为子节点）。"""
    coding_graph = build_coding_graph(app)

    # =====================================================
    # Task Scheduler
    # =====================================================

    async def scheduler_node(state: dict) -> dict:
        # ---- 人工打断安全点（HITL：任务级 pause/resume）----
        await pause_safe_point(app, state, "任务调度")

        tasks = tasks_of(state)
        scratch = dict(state.get("scratch") or {})

        # 依赖修复后恢复：BLOCKED 任务的依赖不再失败 → 回到 PENDING
        failed_ids = {t.id for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)}
        for t in tasks:
            if t.status == TaskStatus.BLOCKED and all(dep not in failed_ids for dep in t.dependencies):
                t.status = TaskStatus.PENDING
        tasks = propagate_blocking(tasks)

        ready = compute_ready_tasks(tasks)
        by_id = {t.id: t for t in tasks}
        topo = topological_order(tasks)
        ordered_ready = [tid for tid in topo if tid in ready]
        newly_ready: list[str] = []
        for tid in ready:
            if by_id[tid].status != TaskStatus.READY:
                newly_ready.append(tid)
            by_id[tid].status = TaskStatus.READY

        async with app.database.session() as session_db:
            await repo.sync_tasks(session_db, state["run_id"], tasks)
        for tid in newly_ready:
            await app.tracer.emit(state["run_id"], EventType.TASK_READY, f"Task {tid} ready.", agent="task_scheduler")

        completed_all = bool(tasks) and all(t.status == TaskStatus.COMPLETED for t in tasks)
        blocked_left = [t for t in tasks if t.status in (TaskStatus.BLOCKED, TaskStatus.FAILED)]

        updates: dict = {
            "task_dag": dump_tasks(tasks),
            "ready_tasks": ordered_ready,
            "current_agent": "task_scheduler",
        }
        if completed_all:
            scratch["dev_stage"] = "test"
            await app.tracer.emit(
                state["run_id"], EventType.LOG, "All tasks completed. Running integration tests...", agent="scheduler"
            )
        elif ordered_ready:
            scratch["dev_stage"] = "code"
            updates["active_task_id"] = ordered_ready[0]
        elif blocked_left:
            scratch["dev_stage"] = "blocked"
            names = ", ".join(f"{t.id}({t.status.value})" for t in blocked_left[:8])
            updates["needs_human"] = True
            updates["fail_reason"] = f"任务阻塞/失败且无法继续: {names}"
            updates["errors"] = merged_errors(state, make_error("scheduler", updates["fail_reason"]))
        else:
            scratch["dev_stage"] = "blocked"
            updates["needs_human"] = True
            updates["fail_reason"] = "无就绪任务且未全部完成（状态异常）"
            updates["errors"] = merged_errors(state, make_error("scheduler", updates["fail_reason"]))
        updates["scratch"] = scratch
        return updates

    # =====================================================
    # Task 完成收尾
    # =====================================================

    async def finalize_task_node(state: dict) -> dict:
        tasks = tasks_of(state)
        scratch = dict(state.get("scratch") or {})
        active_id = state.get("active_task_id") or ""
        task = next((t for t in tasks if t.id == active_id), None)
        updates: dict = {}
        if task is None:
            scratch["finalize_route"] = "blocked"
            updates["needs_human"] = True
            updates["fail_reason"] = "finalize_task 找不到活动任务"
            updates["scratch"] = scratch
            return updates

        coding_result = scratch.get("coding_result") or {}
        validation = scratch.get("validation") or {}
        if coding_result.get("status") == "done" and validation.get("passed"):
            task.status = TaskStatus.COMPLETED
            task.result_summary = str(coding_result.get("summary", ""))[:500]
            completed = list(dict.fromkeys(list(state.get("completed_tasks") or []) + [task.id]))
            scratch["finalize_route"] = "schedule"
            updates["completed_tasks"] = completed
            await app.tracer.emit(
                state["run_id"], EventType.TASK_COMPLETED, f"Task {task.id} completed.", agent="coder"
            )
        else:
            task.status = TaskStatus.FAILED
            reason = (
                str(coding_result.get("notes", ""))
                or str(validation.get("reason", ""))
                or str(validation.get("error", ""))
            )[:400]
            task.error = reason
            await app.tracer.emit(
                state["run_id"],
                EventType.TASK_FAILED,
                f"Task {task.id} failed: {reason[:160]}",
                agent="coder",
            )
            if task.attempts < app.settings.max_code_retry:
                scratch["finalize_route"] = "repair"
                scratch["repair_from"] = "code"
                scratch["active_task_id"] = task.id
            else:
                scratch["finalize_route"] = "blocked"
                updates["needs_human"] = True
                updates["fail_reason"] = (
                    f"任务 {task.id} 达到 MAX_CODE_RETRY={app.settings.max_code_retry} 仍失败"
                )
                updates["errors"] = merged_errors(state, make_error("coder", updates["fail_reason"]))

        async with app.database.session() as session_db:
            await repo.upsert_task(session_db, state["run_id"], task)
        updates.update(
            {
                "task_dag": dump_tasks(tasks),
                "scratch": scratch,
                "current_agent": "coder",
            }
        )
        return updates

    # =====================================================
    # Repair（修复路由入口）
    # =====================================================

    async def repair_node(state: dict) -> dict:
        tasks = tasks_of(state)
        scratch = dict(state.get("scratch") or {})
        stage = scratch.get("repair_from") or "code"
        active_id = scratch.get("active_task_id") or state.get("active_task_id") or ""
        topo = topological_order(tasks)
        target = next((t for t in tasks if t.id == active_id), None)
        if target is None:
            # 未指定修复目标：选择拓扑序最后一个已完成任务
            completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
            if completed:
                target = sorted(completed, key=lambda t: topo.index(t.id))[-1]
            elif tasks:
                target = sorted(tasks, key=lambda t: topo.index(t.id))[-1]

        updates: dict = {"current_agent": "repair"}
        if target is None:
            scratch["repair_route"] = "blocked"
            updates["needs_human"] = True
            updates["fail_reason"] = "修复阶段找不到目标任务"
            updates["scratch"] = scratch
            return updates

        if target.attempts >= app.settings.max_code_retry:
            scratch["repair_route"] = "blocked"
            updates["needs_human"] = True
            updates["fail_reason"] = (
                f"任务 {target.id} 修复次数达到 MAX_CODE_RETRY={app.settings.max_code_retry}"
            )
            updates["errors"] = merged_errors(state, make_error("repair", updates["fail_reason"]))
            updates["task_dag"] = dump_tasks(tasks)
            updates["scratch"] = scratch
            return updates

        target.status = TaskStatus.READY
        scratch["feedback"] = _compose_feedback(state, stage)
        scratch["repair_route"] = "code"
        scratch["dev_stage"] = "code"
        scratch["active_task_id"] = target.id
        await app.tracer.emit(
            state["run_id"], EventType.REPAIRING, f"Repairing {target.id} (from {stage})...", agent="coder"
        )
        async with app.database.session() as session_db:
            await repo.upsert_task(session_db, state["run_id"], target)
        updates.update(
            {
                "task_dag": dump_tasks(tasks),
                "active_task_id": target.id,
                "scratch": scratch,
                "retry_count": int(state.get("retry_count") or 0) + 1,
            }
        )
        return updates

    # =====================================================
    # Testing
    # =====================================================

    async def testing_node(state: dict) -> dict:
        updates = await run_tester(app, state)
        report = updates.get("test_results") or {}
        scratch = dict(state.get("scratch") or {})
        retries = dict(state.get("retries") or {"code": 0, "test": 0, "review": 0, "plan": 0})
        if report.get("passed"):
            scratch["test_route"] = "review"
        else:
            retries["test"] = retries.get("test", 0) + 1
            if retries["test"] > app.settings.max_test_retry:
                scratch["test_route"] = "blocked"
                updates["needs_human"] = True
                updates["fail_reason"] = (
                    f"测试失败且重试达到 MAX_TEST_RETRY={app.settings.max_test_retry}"
                )
                updates["errors"] = merged_errors(state, make_error("tester", updates["fail_reason"]))
            else:
                scratch["test_route"] = "repair"
                scratch["repair_from"] = "test"
                scratch["active_task_id"] = state.get("active_task_id") or ""
                updates["retry_count"] = int(state.get("retry_count") or 0) + 1
        updates["scratch"] = scratch
        updates["retries"] = retries
        return updates

    # =====================================================
    # Review
    # =====================================================

    async def review_node(state: dict) -> dict:
        updates = await run_reviewer(app, state)
        report = updates.get("review_results") or {}
        scratch = dict(state.get("scratch") or {})
        retries = dict(state.get("retries") or {"code": 0, "test": 0, "review": 0, "plan": 0})
        if report.get("approved"):
            scratch["review_route"] = "done"
            updates["dev_cycle_done"] = True
        else:
            retries["review"] = retries.get("review", 0) + 1
            if retries["review"] > app.settings.max_review_retry:
                scratch["review_route"] = "blocked"
                updates["needs_human"] = True
                updates["fail_reason"] = (
                    f"Review 未通过且重试达到 MAX_REVIEW_RETRY={app.settings.max_review_retry}"
                )
                updates["errors"] = merged_errors(state, make_error("reviewer", updates["fail_reason"]))
            else:
                scratch["review_route"] = "repair"
                scratch["repair_from"] = "review"
                scratch["active_task_id"] = state.get("active_task_id") or ""
                updates["retry_count"] = int(state.get("retry_count") or 0) + 1
        updates["scratch"] = scratch
        updates["retries"] = retries
        return updates

    # =====================================================
    # 图结构
    # =====================================================

    routes = {**DEV_ROUTES, "done": END, "blocked": END}
    graph = StateGraph(DevState)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("code_task", coding_graph)
    graph.add_node("finalize_task", finalize_task_node)
    graph.add_node("repair", repair_node)
    graph.add_node("testing", testing_node)
    graph.add_node("review", review_node)

    graph.add_edge(START, "scheduler")
    graph.add_conditional_edges("scheduler", route_after_scheduler, routes)
    graph.add_edge("code_task", "finalize_task")
    graph.add_conditional_edges("finalize_task", route_after_finalize, routes)
    graph.add_conditional_edges("repair", route_after_repair, routes)
    graph.add_conditional_edges("testing", route_after_testing, routes)
    graph.add_conditional_edges("review", route_after_review, routes)
    return graph.compile()
