"""Long-term Memory：跨任务知识复用（FR-MEM-03/05，V2 完整实现）。

Architecture Decision Records / Common Project Patterns / Frequently Seen Errors /
Stable User Preferences。MVP 提供最小可用的文件持久化实现。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class LongTermMemory:
    """按项目存储长期记忆（JSON 文件，data/artifacts/<project_id>/long_term.json）。"""

    def __init__(self, root: Path, project_id: str):
        self.root = root / project_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "long_term.json"
        self.data: dict[str, list[dict[str, Any]]] = {"adrs": [], "patterns": [], "errors": [], "preferences": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass

    def _persist(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------- ADR（Architecture Decision Records） ----------

    def add_adr(self, title: str, decision: str, rationale: str = "") -> None:
        self.data["adrs"].append({"title": title, "decision": decision, "rationale": rationale, "ts": time.time()})
        self._persist()

    # ---------- 常见错误模式 ----------

    def add_error_pattern(self, signature: str, resolution: str = "") -> None:
        for item in self.data["errors"]:
            if item.get("signature") == signature:
                item["count"] = item.get("count", 1) + 1
                if resolution:
                    item["resolution"] = resolution
                self._persist()
                return
        self.data["errors"].append({"signature": signature, "resolution": resolution, "count": 1, "ts": time.time()})
        self._persist()

    # ---------- 读取 ----------

    def excerpt(self, max_chars: int = 1200) -> str:
        parts: list[str] = []
        if self.data["adrs"]:
            parts.append(
                "ADRs:\n"
                + "\n".join(f"- {a['title']}: {a['decision'][:120]}" for a in self.data["adrs"][-5:])
            )
        if self.data["errors"]:
            parts.append(
                "Frequent Errors:\n"
                + "\n".join(
                    f"- {e['signature'][:120]} → {e.get('resolution', '')[:120]}" for e in self.data["errors"][-5:]
                )
            )
        return "\n".join(parts)[:max_chars]

    def search_errors(self, keyword: str) -> Optional[dict[str, Any]]:
        for item in reversed(self.data["errors"]):
            if keyword.lower() in item.get("signature", "").lower():
                return item
        return None
