"""Agent 公共辅助：状态更新、仓库概览、错误记录。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.agents.prompts import SYSTEM_PROMPTS
from app.schemas.state import DevState, TaskRecord
from app.services.app_context import AppContext


def workspace_of(state: dict) -> Path:
    path = state.get("workspace_path") or ""
    if not path:
        raise RuntimeError("Shared State 缺少 workspace_path")
    return Path(path)


def merged_errors(state: dict, *items: dict) -> list:
    """错误列表读改写（errors 采用覆盖语义，避免子图双写）。"""
    current = list(state.get("errors") or [])
    current.extend(items)
    return current


def make_error(stage: str, message: str, **extra: Any) -> dict:
    return {"stage": stage, "message": message, "ts": time.time(), **extra}


def append_history(state: dict, entry: dict) -> list:
    current = list(state.get("supervisor_history") or [])
    current.append(entry)
    return current


def bump_retry(state: dict, key: str) -> dict[str, int]:
    retries = dict(state.get("retries") or {"code": 0, "test": 0, "review": 0, "plan": 0})
    retries[key] = retries.get(key, 0) + 1
    return retries


def tasks_of(state: dict) -> list[TaskRecord]:
    return [TaskRecord.model_validate(t) for t in (state.get("task_dag") or [])]


def dump_tasks(tasks: list[TaskRecord]) -> list[dict]:
    return [t.model_dump(mode="json") for t in tasks]


def agent_prompt(agent: str) -> str:
    return SYSTEM_PROMPTS[agent]


def ctx_factory_for(app: AppContext, state: dict, agent: str) -> Callable:
    return app.make_ctx_factory(
        run_id=state["run_id"],
        project_id=state["project_id"],
        agent=agent,
        workspace=workspace_of(state),
    )


# =========================================================
# 仓库概览（供 Product / Architect / Reviewer 上下文）
# =========================================================


def build_repo_overview(workspace: Path, max_chars: int = 2500) -> str:
    parts: list[str] = []
    try:
        top = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in workspace.iterdir()
            if p.name not in {".git", ".venv", "__pycache__", "node_modules"}
        )
        parts.append("Top-level entries: " + ", ".join(top[:40]))
    except OSError:
        return "(无法读取仓库目录)"
    # README 摘要
    for name in ("README.md", "README.rst", "README.txt"):
        readme = workspace / name
        if readme.is_file():
            try:
                text = readme.read_text(encoding="utf-8", errors="replace")
                head = "\n".join(text.splitlines()[:40])
                parts.append(f"--- {name} (前 40 行) ---\n{head}")
            except OSError:
                pass
            break
    # 源码结构（两层）
    src_lines: list[str] = []
    for pattern in ("*.py", "*.ts", "*.js", "*.tsx", "*.jsx"):
        for path in sorted(workspace.rglob(pattern)):
            rel = path.relative_to(workspace)
            if any(part in {".git", ".venv", "node_modules", "__pycache__", "dist", "build"} for part in rel.parts):
                continue
            if rel.parts and rel.parts[0] in {"app", "src", "tests", "test", "lib"}:
                src_lines.append(str(rel.as_posix()))
            if len(src_lines) >= 120:
                break
        if len(src_lines) >= 120:
            break
    if src_lines:
        parts.append("Source files (部分):\n" + "\n".join(src_lines[:120]))
    return "\n\n".join(parts)[:max_chars]


def format_task_brief(task: TaskRecord, extra: Optional[str] = None) -> str:
    lines = [
        f"Task {task.id}: {task.title}",
        f"Description: {task.description}",
    ]
    if task.dependencies:
        lines.append(f"Depends on: {', '.join(task.dependencies)}")
    if task.acceptance_criteria:
        lines.append("Acceptance Criteria:\n" + "\n".join(f"- {a}" for a in task.acceptance_criteria))
    if extra:
        lines.append(extra)
    return "\n".join(lines)
