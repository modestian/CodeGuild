"""ContextManager：为每次模型调用构造最必要上下文。

对应需求：FR-CTX-01~05、NFR-PERF-02：
- 最小必要上下文：System Prompt + Current Task + Acceptance Criteria + Architecture
  Constraints + Relevant Code Chunks + Recent Tool Results + Current Errors
- 不把整个代码库放入 Prompt
- Compaction（V2 基线已实现）：超阈值时对历史消息与工具输出摘要压缩，保留决策、结论、文件路径
"""
from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.harness.session import RuntimeSession
from app.schemas.tool import ToolDef

Message = dict[str, Any]


def estimate_tokens(text: str) -> int:
    """粗略 Token 估算（中文约 1 字 1 token，英文约 4 字符 1 token）。"""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + non_ascii)


def estimate_messages_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(str(m.get("content", ""))) + 8 for m in messages)


def normalize_tool_messages(messages: list[Message]) -> list[Message]:
    """规范化工具消息配对（OpenAI 协议要求 tool 消息必须响应前置 assistant.tool_calls）。

    处理两类非法形态（如压缩边界 / 旧格式会话产生）：
    1. assistant.tool_calls 中未被紧随其后的 tool 消息响应的条目 → 从 tool_calls 中剔除；
    2. 找不到配对声明的孤儿 tool 消息 → 降级为 user 消息（保留观察内容）。
    仅在确有需要修复的消息时返回新列表，否则原样返回。
    """
    changed = False
    n = len(messages)
    # Pass 1：剔除未被响应的 tool_calls 条目
    working: list[Message] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            responded: set[Any] = set()
            j = i + 1
            while j < n and messages[j].get("role") == "tool":
                responded.add(messages[j].get("tool_call_id"))
                j += 1
            kept = [tc for tc in msg["tool_calls"] if tc.get("id") in responded]
            if len(kept) != len(msg["tool_calls"]):
                changed = True
                copy = dict(msg)
                if kept:
                    copy["tool_calls"] = kept
                else:
                    copy.pop("tool_calls", None)
                working.append(copy)
                continue
        working.append(msg)

    # Pass 2：孤儿 tool 消息降级为 user
    declared: set[Any] = set()
    result: list[Message] = []
    for msg in working:
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                if tc.get("id"):
                    declared.add(tc["id"])
            result.append(msg)
            continue
        if role == "tool":
            tid = msg.get("tool_call_id")
            if tid and tid in declared:
                declared.discard(tid)
                result.append(msg)
            else:
                changed = True
                tool_name = msg.get("name", "tool")
                result.append(
                    {
                        "role": "user",
                        "content": f"[工具结果 {tool_name}] {str(msg.get('content', ''))}",
                    }
                )
            continue
        result.append(msg)
    return result if changed else messages


class ContextManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    # =====================================================
    # 装配
    # =====================================================

    def tool_manifest(self, defs: list[ToolDef]) -> str:
        """工具清单（名称 + 描述 + 精简输入 Schema）。"""
        lines: list[str] = []
        for d in defs:
            schema = d.input_schema or {}
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            params = []
            for name, prop in props.items():
                ptype = prop.get("type", "any")
                if ptype == "array":
                    ptype = "array"
                marker = "" if name in required else "?"
                params.append(f"{name}{marker}:{ptype}")
            lines.append(f"- {d.name}({', '.join(params)}): {d.description}")
        return "\n".join(lines)

    def initial_messages(
        self,
        system_prompt: str,
        task_brief: str,
        memory_excerpt: str = "",
        working_memory: str = "",
    ) -> list[Message]:
        system = system_prompt
        if memory_excerpt:
            system += f"\n\n## Project Memory\n{memory_excerpt}"
        user_parts = [f"## Current Task\n{task_brief}"]
        if working_memory:
            user_parts.append(f"## Working Memory\n{working_memory}")
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    # =====================================================
    # Compaction（FR-CTX-03）
    # =====================================================

    def prepare(self, session: RuntimeSession, budget_tokens: int | None = None) -> list[Message]:
        """返回（可能已压缩的）消息列表；压缩结果写回 session.messages。"""
        budget = budget_tokens or self.settings.context_max_tokens
        messages = session.messages
        if estimate_messages_tokens(messages) <= budget:
            return normalize_tool_messages(messages)

        keep_head = messages[:2]  # system + task
        rest = messages[2:]
        tail_budget = int(budget * 0.75)
        tail: list[Message] = []
        used = estimate_messages_tokens(keep_head)
        for msg in reversed(rest):
            cost = estimate_tokens(str(msg.get("content", ""))) + 8
            if used + cost > tail_budget and tail:
                break
            tail.insert(0, msg)
            used += cost
        dropped = rest[: len(rest) - len(tail)]
        summary = self._summarize_dropped(dropped)
        compacted = list(keep_head)
        if summary:
            compacted.append(
                {"role": "user", "content": f"## 历史压缩摘要（Compaction，保留决策与结论）\n{summary}"}
            )
        compacted.extend(tail)
        session.messages = compacted
        return normalize_tool_messages(compacted)

    def _summarize_dropped(self, dropped: list[Message]) -> str:
        lines: list[str] = []
        for msg in dropped:
            role = msg.get("role")
            content = str(msg.get("content", ""))
            if role == "tool":
                status = "ok"
                detail = content[:120]
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        status = str(parsed.get("status", "ok"))
                        if parsed.get("summary"):
                            detail = json.dumps(parsed["summary"], ensure_ascii=False)[:120]
                        elif parsed.get("error"):
                            detail = str(parsed["error"])[:120]
                except (ValueError, TypeError):
                    pass
                lines.append(f"- [{msg.get('name', 'tool')}] {status}: {detail}")
            elif role == "assistant":
                rationale = ""
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        rationale = str(parsed.get("rationale", ""))[:140]
                        if parsed.get("decision") == "tool_call":
                            rationale = f"tool_call {parsed.get('tool')} — {rationale}"
                except (ValueError, TypeError):
                    rationale = content[:140]
                if rationale:
                    lines.append(f"- (agent) {rationale}")
        text = "\n".join(lines)
        return text[:4000]
