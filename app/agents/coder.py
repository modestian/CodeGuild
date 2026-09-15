"""Coding Agent：真实代码修改（FR-CODE-01~09）。

标准工作流：Task → Repository Exploration → Code Retrieval → Read → Plan → Edit →
Run Validation → Inspect → Fix / Finish。
本模块提供编码子图所需的能力：上下文检索、任务简报、单次编码执行。
"""
from __future__ import annotations

import json
from typing import Optional

from app.agents.base import agent_prompt, ctx_factory_for, format_task_brief, workspace_of
from app.harness.runtime import AgentRunResult, AgentRuntime
from app.harness.session import RuntimeSession
from app.retrieval.bm25 import build_index
from app.schemas.artifacts import CoderFinal
from app.schemas.state import TaskRecord
from app.services.app_context import AppContext

MAX_RETRIEVAL_CHUNKS = 6
MAX_RETRIEVAL_CHARS = 4000


def session_id_for(run_id: str, task_id: str) -> str:
    return f"{run_id}:coder:{task_id}"


def load_or_create_session(app: AppContext, run_id: str, task_id: str) -> RuntimeSession:
    session = app.sessions.load(run_id, session_id_for(run_id, task_id))
    if session is None:
        session = RuntimeSession(
            session_id=session_id_for(run_id, task_id),
            run_id=run_id,
            agent="coder",
            task_id=task_id,
        )
    return session


def retrieve_context(workspace, task: TaskRecord, max_chars: int = MAX_RETRIEVAL_CHARS) -> str:
    """Repository Exploration 之前的 Code Retrieval（FR-CODE-02）。"""
    query = f"{task.title} {task.description} {' '.join(task.acceptance_criteria or [])}"
    try:
        index = build_index(workspace, max_files=300, max_bytes_per_file=200_000)
        results = index.search(query, top_k=MAX_RETRIEVAL_CHUNKS)
    except Exception:  # noqa: BLE001 —— 检索失败不阻断编码
        return ""
    if not results:
        return ""
    parts: list[str] = []
    for scored in results:
        chunk = scored.chunk
        parts.append(f"--- {chunk.file} (L{chunk.start_line}-{chunk.end_line}, score={scored.score}) ---\n{chunk.text}")
    return "\n\n".join(parts)[:max_chars]


def build_coder_brief(
    task: TaskRecord,
    retrieval: str,
    feedback: str = "",
    context_extra: str = "",
) -> str:
    extras: list[str] = []
    if retrieval:
        extras.append(f"## Relevant Code Context（Code Retrieval 结果，供参考）\n{retrieval}")
    if context_extra:
        extras.append(context_extra)
    if feedback:
        extras.append(
            "## 上次验证未通过（Repair 反馈，必须解决）\n" + feedback
        )
    extras.append(
        "## 要求\n"
        "1) 先用 list_files / search_code / read_symbol 探索并阅读相关代码；\n"
        "2) 必须先用 update_plan 记录计划；\n"
        "3) 再进行编辑（edit_file / create_file / apply_patch）；\n"
        "4) 修改后执行 run_test 验证；失败则修复后重测；\n"
        "5) 完成后输出 final（CoderFinal）：status/summary/changed_files/validation/notes。"
    )
    return format_task_brief(task, "\n\n".join(extras))


async def run_coder_once(
    app: AppContext,
    state: dict,
    task: TaskRecord,
    session: RuntimeSession,
    feedback: str = "",
    retrieval: str = "",
) -> AgentRunResult:
    """执行一次编码循环（含内部工具循环与修复）；可从中断会话恢复。"""
    workspace = workspace_of(state)
    runtime: AgentRuntime = app.runtime

    # 恢复会话时追加修复反馈（若尚未追加）
    if feedback and session.messages:
        last = session.messages[-1]
        marker = feedback[:200]
        if not (isinstance(last, dict) and marker in str(last.get("content", ""))):
            session.add_message("user", f"## 修复要求\n{feedback}")

    if not session.messages:
        if not retrieval:
            retrieval = retrieve_context(workspace, task)
        brief = build_coder_brief(task, retrieval)
        session.messages = app.context_manager.initial_messages(
            agent_prompt("coder"),
            brief,
            memory_excerpt="",
            working_memory="",
        )
        app.sessions.save(session)

    result = await runtime.run(
        run_id=state["run_id"],
        agent="coder",
        system_prompt=agent_prompt("coder"),
        task_brief="",  # 会话已初始化时忽略
        ctx_factory=ctx_factory_for(app, state, "coder"),
        output_schema=CoderFinal,
        mode="agentic",
        session=session,
        task_id=task.id,
    )
    return result


def merge_changed_files(state: dict, session: RuntimeSession, task_id: str) -> list[dict]:
    """将会话内修改过的文件合并进 Shared State（changed_files）。"""
    current: dict[str, dict] = {}
    for item in state.get("changed_files") or []:
        if isinstance(item, dict) and item.get("path"):
            current[item["path"]] = item
    for path, action in session.changed_files.items():
        current[path] = {"path": path, "action": action, "task_id": task_id}
    return list(current.values())


def parse_final(result: AgentRunResult) -> CoderFinal:
    if result.final_output:
        try:
            return CoderFinal.model_validate(result.final_output)
        except Exception:  # noqa: BLE001
            pass
    return CoderFinal(
        status="blocked",
        summary="",
        changed_files=[],
        notes=(result.error or result.stopped_reason or "coder did not return a final output")[:500],
    )
