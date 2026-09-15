"""Working Memory：当前 Agent 的工作记忆（FR-MEM-01）。

Current Task / Recent Tool Calls / Recent Errors / Current Plan。
由 RuntimeSession 派生，不额外持久化。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.harness.session import RuntimeSession


class WorkingMemory(BaseModel):
    current_task: str = ""
    recent_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    recent_errors: list[str] = Field(default_factory=list)
    current_plan: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_session(cls, session: RuntimeSession, current_task: str = "") -> "WorkingMemory":
        calls: list[dict[str, Any]] = []
        errors: list[str] = []
        for msg in session.messages:
            if msg.get("role") == "tool":
                content = str(msg.get("content", ""))
                brief = content[:220]
                calls.append({"tool": msg.get("name", ""), "brief": brief})
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and parsed.get("status") == "error":
                        errors.append(f"{msg.get('name')}: {str(parsed.get('error'))[:200]}")
                except (ValueError, TypeError):
                    pass
        return cls(
            current_task=current_task or session.task_id,
            recent_tool_calls=calls[-10:],
            recent_errors=errors[-5:],
            current_plan=session.plan or {},
        )

    def to_text(self, max_chars: int = 2000) -> str:
        parts: list[str] = []
        if self.current_task:
            parts.append(f"Current Task: {self.current_task}")
        if self.current_plan:
            plan_brief = self.current_plan.get("approach") or ""
            files = self.current_plan.get("files_to_change") or []
            parts.append(f"Current Plan: {plan_brief}" + (f" | files: {', '.join(files[:6])}" if files else ""))
        if self.recent_tool_calls:
            calls = "; ".join(f"{c['tool']}({c['brief'][:60]})" for c in self.recent_tool_calls[-6:])
            parts.append(f"Recent Tool Calls: {calls}")
        if self.recent_errors:
            parts.append("Recent Errors:\n" + "\n".join(f"- {e}" for e in self.recent_errors[-3:]))
        return "\n".join(parts)[:max_chars]
