"""运行时会话（RuntimeSession）：单次 Agent 执行循环的可持久化工作记忆。

用途：
1. Working Memory（FR-MEM-01）：Current Task / Recent Tool Calls / Recent Errors / Current Plan
2. 中断安全：审批中断（interrupt）后恢复时，从持久化会话继续，不重复已完成的工具调用
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class RuntimeSession(BaseModel):
    """Agent 会话：跨执行段保留的对话记忆 + 按执行段管理的预算计数器。

    - 对话记忆（messages / plan / changed_files / pending_calls）跨执行段保留；
    - 预算计数器（steps / tool_failures / tokens / cost / started_ts）仅在单个执行段内累计，
      新执行段开始时由 AgentRuntime 重置（AgentRuntime._reset_execution_budget），
      避免 token 到顶 / 轮次上限后「继续迭代」立即再次命中停止条件。
    """

    session_id: str
    run_id: str = ""
    agent: str = ""
    task_id: str = ""
    status: str = "running"  # running | awaiting_approval | finished | failed
    messages: list[dict[str, Any]] = Field(default_factory=list)
    steps: int = 0
    tool_failures: int = 0
    plan: dict[str, Any] = Field(default_factory=dict)
    changed_files: dict[str, str] = Field(default_factory=dict)  # path -> action
    # 待执行的原生 function calling 工具调用批次（中断安全：审批中断后从此处恢复）
    # 项格式：{"id": <tool_call_id>, "name": <工具名>, "arguments": {...}}
    pending_calls: list[dict[str, Any]] = Field(default_factory=list)
    pending_call: Optional[dict[str, Any]] = None  # 兼容旧会话数据（已废弃，新逻辑使用 pending_calls）
    final_output: Optional[dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    started_ts: float = Field(default_factory=time.time)
    error: str = ""

    # ---------- 便捷方法 ----------

    def add_message(self, role: str, content: str, **extra: Any) -> None:
        msg: dict[str, Any] = {"role": role, "content": content}
        msg.update(extra)
        self.messages.append(msg)

    def recent_tool_calls(self, n: int = 10) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("role") == "tool"][-n:]

    def wall_time(self) -> float:
        return max(0.0, time.time() - self.started_ts)


class SessionStore:
    """会话持久化：内存缓存 + JSON 文件（data/sessions/{run_id}/{session_id}.json）。"""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, RuntimeSession] = {}

    def _path(self, session: RuntimeSession) -> Path:
        d = self.root / session.run_id
        d.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r'[<>:"/\\|?*]', "_", session.session_id)
        return d / f"{safe_id}.json"

    def save(self, session: RuntimeSession) -> None:
        self._cache[session.session_id] = session
        path = self._path(session)
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")

    def load(self, run_id: str, session_id: str) -> Optional[RuntimeSession]:
        if session_id in self._cache:
            return self._cache[session_id]
        safe_id = re.sub(r'[<>:"/\\|?*]', "_", session_id)
        path = self.root / run_id / f"{safe_id}.json"
        if path.exists():
            session = RuntimeSession.model_validate_json(path.read_text(encoding="utf-8"))
            self._cache[session_id] = session
            return session
        return None

    def drop(self, session_id: str) -> None:
        session = self._cache.pop(session_id, None)
        if session is not None:
            path = self._path(session)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
