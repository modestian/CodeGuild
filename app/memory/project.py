"""Project Memory：项目级记忆（FR-MEM-02 / FR-MEM-04）。

Requirements / Architecture / Task Status / Coding Conventions / Important Decisions。
经 ContextManager 装配后注入模型调用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

CONVENTION_FILES = ["AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md", "pyproject.toml"]


class ProjectMemory:
    """项目记忆：从共享状态与工作区文件装配。"""

    def __init__(
        self,
        *,
        requirements: Optional[dict[str, Any]] = None,
        architecture: Optional[dict[str, Any]] = None,
        task_dag: Optional[list] = None,
        decisions: Optional[list[str]] = None,
    ):
        self.requirements = requirements or {}
        self.architecture = architecture or {}
        self.task_dag = task_dag or []
        self.decisions = decisions or []
        self._conventions_cache: Optional[str] = None

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "ProjectMemory":
        decisions: list[str] = []
        for item in state.get("supervisor_history", [])[-10:]:
            if isinstance(item, dict) and item.get("reason"):
                decisions.append(f"{item.get('next_agent')}: {item.get('reason')}")
        return cls(
            requirements=state.get("requirements") or {},
            architecture=state.get("architecture") or {},
            task_dag=state.get("task_dag") or [],
            decisions=decisions,
        )

    # ---------- Coding Conventions ----------

    def coding_conventions(self, workspace: Path, max_chars: int = 1500) -> str:
        if self._conventions_cache is not None:
            return self._conventions_cache
        excerpts: list[str] = []
        for name in CONVENTION_FILES:
            path = workspace / name
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                head = "\n".join(text.splitlines()[:60])
                excerpts.append(f"--- {name} (摘要) ---\n{head}")
            if len("\n".join(excerpts)) > max_chars:
                break
        self._conventions_cache = "\n".join(excerpts)[:max_chars]
        return self._conventions_cache

    # ---------- 装配输出 ----------

    def excerpt(self, max_chars: int = 2500) -> str:
        parts: list[str] = []
        if self.requirements:
            summary = self.requirements.get("summary") or ""
            features = self.requirements.get("features") or []
            acs = self.requirements.get("acceptance_criteria") or []
            parts.append(
                "Requirements:\n"
                + (f"{summary}\n" if summary else "")
                + "Features: " + "; ".join(str(f.get("name", f)) if isinstance(f, dict) else str(f) for f in features[:8])
                + ("\nAC: " + "; ".join(str(a.get("description", a)) if isinstance(a, dict) else str(a) for a in acs[:8]) if acs else "")
            )
        if self.architecture:
            parts.append(
                "Architecture:\n"
                + (self.architecture.get("design_overview") or self.architecture.get("summary") or "")[:800]
                + "\nModules: "
                + ", ".join(
                    str(m.get("name", m)) if isinstance(m, dict) else str(m)
                    for m in (self.architecture.get("modules") or [])[:10]
                )
            )
        if self.task_dag:
            statuses: dict[str, int] = {}
            for t in self.task_dag:
                status = t.get("status", "PENDING") if isinstance(t, dict) else str(t)
                statuses[status] = statuses.get(status, 0) + 1
            parts.append("Task Status: " + json.dumps(statuses, ensure_ascii=False))
        if self.decisions:
            parts.append("Important Decisions:\n" + "\n".join(f"- {d}" for d in self.decisions[-5:]))
        return "\n\n".join(parts)[:max_chars]
