"""Coding SubGraph（FR-LG-05、FR-CODE-01~09）。

Receive Task → Retrieve Context → Explore Repository → Generate Plan → Edit Code →
Run Validation →（NO: Repair / YES: Finish）

Explore / Plan / Edit 由 Coding Agent 在 Harness 执行循环内完成（工具调用驱动），
本子图负责：任务接收、上下文检索、执行、确定性验证与修复路由。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents import coder as coder_agent
from app.agents.base import ctx_factory_for, dump_tasks, tasks_of, workspace_of
from app.graph.routing import route_after_validation
from app.harness.session import RuntimeSession
from app.schemas.events import EventType
from app.schemas.state import DevState, TaskStatus
from app.schemas.tool import ToolCall
from app.services.app_context import AppContext
from app.storage import repositories as repo


def _active_task(state: dict):
    tasks = tasks_of(state)
    active_id = state.get("active_task_id") or ""
    task = next((t for t in tasks if t.id == active_id), None)
    return tasks, task


def _brief_arguments(args: Any, limit: int = 800) -> dict:
    """审批载荷中的参数截断（大文本只保留摘要，避免前端渲染与事件膨胀）。"""
    brief: dict = {}
    for key, value in (args or {}).items():
        if isinstance(value, str) and len(value) > limit:
            brief[key] = value[:limit] + f"...(共 {len(value)} 字符)"
        elif isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
            brief[key] = value if len(text) <= limit else text[:limit] + f"...(共 {len(text)} 字符)"
        else:
            brief[key] = value
    return brief


def _validation_feedback(validation: dict) -> str:
    lines = ["验证未通过（run_test 失败），请定位根因并修复后重新验证："]
    summary = validation.get("summary") or {}
    if summary:
        lines.append(f"summary: {json.dumps(summary, ensure_ascii=False)}")
    for item in (validation.get("failures") or [])[:8]:
        if isinstance(item, dict):
            lines.append(f"- {item.get('test')}: {str(item.get('message', ''))[:220]}")
    if validation.get("error"):
        lines.append(f"错误摘要: {str(validation['error'])[:400]}")
    return "\n".join(lines)


async def run_validation(app: AppContext, state: dict) -> dict:
    """Run Validation（FR-CODE-06）：确定性执行测试命令并结构化解析。"""
    session = RuntimeSession(
        session_id=f"{state['run_id']}:coder:validation:{state.get('active_task_id', '')}",
        run_id=state["run_id"],
        agent="coder",
    )
    ctx = ctx_factory_for(app, state, "coder")(session)
    result = await app.executor.execute(ToolCall(name="run_test", arguments={}), ctx)
    observation = app.observation.adapt("run_test", result)
    passed = bool(observation.get("passed")) if "passed" in observation else bool(result.ok)
    return {
        "passed": passed,
        "command": app.settings.test_command,
        "exit_code": observation.get("exit_code"),
        "summary": observation.get("summary") or {},
        "failures": (observation.get("failures") or [])[:10],
        "error": observation.get("error_summary") or (result.error if not result.ok else ""),
    }


def build_coding_graph(app: AppContext):
    """编译 Coding SubGraph。"""

    async def receive_task(state: dict) -> dict:
        tasks, task = _active_task(state)
        scratch = dict(state.get("scratch") or {})
        if task is None:
            scratch.update(
                {
                    "coding_route": "failed",
                    "coding_result": {"status": "blocked", "summary": "", "notes": "调度器未提供待办任务"},
                }
            )
            return {"scratch": scratch}
        task.status = TaskStatus.RUNNING
        task.assigned_agent = "coder"
        task.attempts += 1
        async with app.database.session() as session_db:
            await repo.upsert_task(session_db, state["run_id"], task)
        scratch["coding_attempts"] = 0
        await app.tracer.emit(
            state["run_id"], EventType.TASK_STARTED, f"Coding Agent started {task.id}.", agent="coder"
        )
        return {
            "task_dag": dump_tasks(tasks),
            "active_task_id": task.id,
            "current_agent": "coder",
            "scratch": scratch,
        }

    async def retrieve_context_node(state: dict) -> dict:
        tasks, task = _active_task(state)
        scratch = dict(state.get("scratch") or {})
        if task is not None:
            workspace = workspace_of(state)
            scratch["retrieval"] = coder_agent.retrieve_context(workspace, task)
        return {"scratch": scratch}

    async def execute_node(state: dict) -> dict:
        tasks, task = _active_task(state)
        scratch = dict(state.get("scratch") or {})
        if task is None:
            scratch["coding_route"] = "failed"
            return {"scratch": scratch}

        session = coder_agent.load_or_create_session(app, state["run_id"], task.id)
        feedback = scratch.get("feedback") or ""
        while True:
            result = await coder_agent.run_coder_once(
                app,
                state,
                task,
                session,
                feedback=feedback,
                retrieval=scratch.get("retrieval", ""),
            )
            feedback = ""  # 仅首次进入时携带修复反馈
            if result.status == "awaiting_approval":
                pending = session.pending_calls[0] if session.pending_calls else {}
                tool_name = str(pending.get("name") or "")
                mode = await app.approvals.mode_for(state["run_id"])
                options = (
                    ["approve_once", "approve_always", "reject"]
                    if mode == "interactive"
                    else ["approve", "reject"]
                )
                reason = (
                    "逐步确认模式：关键操作需人工确认"
                    if mode == "interactive"
                    else "工具调用需要人工审批"
                )
                try:  # 展示 Executor 记录的审批原因（策略/风险等）
                    async with app.database.session() as session_db:
                        record = await repo.find_approval_for_tool(session_db, state["run_id"], tool_name)
                    if record is not None and record.reason:
                        reason = record.reason
                except Exception:  # noqa: BLE001
                    pass
                payload = {
                    "type": "tool_approval",
                    "run_id": state["run_id"],
                    "task_id": task.id,
                    "approval_id": uuid.uuid4().hex,  # 每次挂起唯一，供前端区分多次请求
                    "tool": tool_name,
                    "arguments": _brief_arguments(pending.get("arguments", {})),
                    "reason": reason,
                    "approval_mode": mode,
                    "options": options,
                }
                interrupt(payload)
                continue
            break

        final = coder_agent.parse_final(result)
        scratch["coding_result"] = final.model_dump()
        scratch["coding_status"] = result.status
        scratch["coding_error"] = result.error or result.stopped_reason
        changed = coder_agent.merge_changed_files(state, session, task.id)
        return {
            "scratch": scratch,
            "plan": session.plan,
            "plan_recorded": bool(session.plan),
            "changed_files": changed,
            "current_agent": "coder",
        }

    async def validate_node(state: dict) -> dict:
        scratch = dict(state.get("scratch") or {})
        coding_result = scratch.get("coding_result") or {}
        if coding_result.get("status") != "done":
            validation = {
                "passed": False,
                "skipped": True,
                "reason": f"coding status={coding_result.get('status')}: {str(coding_result.get('notes', ''))[:200]}",
            }
            scratch["coding_route"] = "failed"
        else:
            validation = await run_validation(app, state)
            if validation.get("passed"):
                scratch["coding_route"] = "finish"
            else:
                attempts = int(scratch.get("coding_attempts") or 0)
                # 子图内修复循环上限 1 次；更大范围修复由 Development SubGraph 的重试上限管控
                if attempts < 1 and app.settings.max_code_retry > 1:
                    scratch["coding_attempts"] = attempts + 1
                    scratch["feedback"] = _validation_feedback(validation)
                    scratch["coding_route"] = "repair"
                else:
                    scratch["coding_route"] = "failed"

        scratch["validation"] = validation
        await app.tracer.emit(
            state["run_id"],
            EventType.VALIDATION_RESULT,
            (
                f"Validation passed: {validation.get('command', '')}"
                if validation.get("passed")
                else f"Validation not passed: {str(validation.get('reason') or validation.get('error') or '')[:160]}"
            ),
            agent="coder",
        )
        return {"validation": validation, "scratch": scratch}

    graph = StateGraph(DevState)
    graph.add_node("receive_task", receive_task)
    graph.add_node("retrieve_context", retrieve_context_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)

    graph.add_edge(START, "receive_task")
    graph.add_edge("receive_task", "retrieve_context")
    graph.add_edge("retrieve_context", "execute")
    graph.add_edge("execute", "validate")
    graph.add_conditional_edges(
        "validate", route_after_validation, {"repair": "execute", "finish": END, "failed": END}
    )
    return graph.compile()
