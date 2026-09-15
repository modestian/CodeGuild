"""ObservationAdapter：工具原始结果 → 结构化观察。

对应需求：FR-OBSA-01~05：
- Tool 原始结果不直接全部交给模型（8000 行 pytest 输出必须转换）
- 日志截断与错误摘要
- 结构化输出（status / passed / failed / errors）
- 敏感信息过滤
- 重复信息消除与 Token 压缩
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.schemas.tool import ToolResult

# ---------- 敏感信息模式（FR-OBSA-04 / NFR-SEC-03） ----------

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9\-_]{16,}"),  # OpenAI / 兼容
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}"),  # Anthropic
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),  # Google API Key
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|passwd|access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9/+._\-]{12,})"),
]

# ---------- pytest 统计 ----------

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error[s]?|skipped|xfailed|xpassed|deselected|warnings?)\b")
_FAILED_LINE_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$", re.M)
_DURATION_RE = re.compile(r"in\s+([\d.]+)s")


class ObservationAdapter:
    """将工具结果转换为进入模型上下文的最小必要观察。"""

    def __init__(self, max_chars: int = 6000, tail_lines: int = 60):
        self.max_chars = max_chars
        self.tail_lines = tail_lines

    # =====================================================
    # 主入口
    # =====================================================

    def adapt(self, tool_name: str, result: ToolResult) -> dict[str, Any]:
        """生成结构化观察（进入模型上下文的对象）。"""
        if not result.ok:
            obs = {
                "status": "error",
                "tool": tool_name,
                "error": self.redact((result.error or "unknown error")[:2000]),
                "decision": result.decision.value,
            }
            if result.raw_output:
                text = self.compress(self.redact(result.raw_output))
                text, truncated = self.truncate(text, self.max_chars // 2)
                obs["output"] = text
                if truncated:
                    obs["truncated"] = True
            return obs

        data = result.data
        # 测试类输出 → 结构化解析
        if tool_name in {"run_test", "run_linter", "run_build", "run_command"} and result.raw_output:
            return self._adapt_command_output(tool_name, result)

        obs: dict[str, Any] = {"status": "success", "tool": tool_name}
        if data is not None:
            # 结构化 data 序列化后仍可能超长 → 截断
            payload = self._jsonable(data)
            text = self._dumps(payload)
            text, truncated = self.truncate(text, self.max_chars)
            obs["data"] = self._loads_or_text(text)
            if truncated:
                obs["truncated"] = True
        if result.raw_output:
            text = self.compress(self.redact(result.raw_output))
            text, truncated = self.truncate(text, self.max_chars // 2)
            obs["output"] = text
            if truncated:
                obs["truncated"] = True
        return obs

    # =====================================================
    # 命令/测试输出解析（FR-OBSA-02/03）
    # =====================================================

    def _adapt_command_output(self, tool_name: str, result: ToolResult) -> dict[str, Any]:
        raw = result.raw_output or ""
        data = result.data if isinstance(result.data, dict) else {}
        exit_code = data.get("exit_code")
        stdout = self.redact(str(data.get("stdout", "")))
        stderr = self.redact(str(data.get("stderr", "")))
        combined = f"{stdout}\n{stderr}".strip() or raw

        parsed = self.parse_pytest(combined) if tool_name == "run_test" or "passed" in combined else None

        obs: dict[str, Any] = {
            "status": "success" if (exit_code in (0, None) and data.get("timed_out") is not True) else "failed",
            "tool": tool_name,
        }
        if exit_code is not None:
            obs["exit_code"] = exit_code
        if data.get("timed_out"):
            obs["timed_out"] = True

        if parsed is not None:
            obs["summary"] = parsed["summary"]
            obs["passed"] = parsed["passed"]
            if parsed["failures"]:
                obs["failures"] = parsed["failures"]

        # 输出截断（头部 + 尾部保留，中间省略）
        text = self.compress(combined)
        text, truncated = self.truncate(text, self.max_chars, keep_head=True)
        obs["output"] = text
        if truncated:
            obs["truncated"] = True

        # 失败时给出摘要行（错误摘要）
        if obs["status"] == "failed" and parsed is None:
            tail = "\n".join(text.splitlines()[-8:])
            obs["error_summary"] = tail[:800]
        return obs

    def parse_pytest(self, output: str) -> dict[str, Any]:
        """解析 pytest 输出为 {passed, summary:{total,passed,failed,errors,skipped}, failures:[...]}。"""
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
        # 以最后一行统计为准（pytest 末尾 "=== 3 failed, 49 passed in 12.3s ==="）
        tail_block = "\n".join(output.splitlines()[-15:]) if output else ""
        for m in _COUNT_RE.finditer(tail_block):
            n, kind = int(m.group(1)), m.group(2)
            if kind.startswith("error"):
                counts["errors"] += n
            elif kind == "deselected":
                continue
            elif kind.startswith("warning"):
                continue
            elif kind in counts:
                counts[kind] += n
            elif kind == "xpassed":
                counts["xpassed"] += n

        failures: list[dict[str, Any]] = []
        for m in _FAILED_LINE_RE.finditer(output):
            kind, test_id, message = m.group(1), m.group(2), (m.group(3) or "").strip()
            failures.append({"test": test_id, "message": message[:500]})
            if len(failures) >= 20:
                break

        total = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"]
        has_result = total > 0
        passed = has_result and counts["failed"] == 0 and counts["errors"] == 0
        summary = {
            "total": total,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "errors": counts["errors"],
            "skipped": counts["skipped"],
        }
        return {"passed": passed, "summary": summary, "failures": failures, "has_result": has_result}

    # =====================================================
    # 通用处理
    # =====================================================

    def redact(self, text: str) -> str:
        """敏感信息过滤（FR-OBSA-04）。"""
        for pattern in SECRET_PATTERNS:
            if pattern.groups >= 2:
                text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
            else:
                text = pattern.sub("[REDACTED]", text)
        return text

    def compress(self, text: str) -> str:
        """重复信息消除 + Token 压缩（FR-OBSA-05）。"""
        if not text:
            return text
        lines = text.replace("\r\n", "\n").split("\n")
        out: list[str] = []
        prev_line = None
        repeat = 0
        for line in lines:
            stripped = line.rstrip()
            if stripped == prev_line:
                repeat += 1
                continue
            if repeat > 0:
                out.append(f"    ... ({repeat} 行重复省略)")
                repeat = 0
            out.append(stripped)
            prev_line = stripped
        if repeat > 0:
            out.append(f"    ... ({repeat} 行重复省略)")
        return "\n".join(out)

    def truncate(self, text: str, max_chars: int, keep_head: bool = True) -> tuple[str, bool]:
        """截断：保留头部与尾部（FR-OBSA-02）。"""
        if len(text) <= max_chars:
            return text, False
        if keep_head:
            head = max_chars * 2 // 3
            tail = max_chars - head
            head_text = text[:head]
            tail_text = "\n".join(text.splitlines()[-self.tail_lines:])[-tail:]
            return f"{head_text}\n... [输出截断，共 {len(text)} 字符] ...\n{tail_text}", True
        return text[:max_chars] + f"\n... [输出截断，共 {len(text)} 字符] ...", True

    def _jsonable(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._jsonable(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._jsonable(v) for v in data[:200]]
        if isinstance(data, str):
            return data
        return data

    @staticmethod
    def _dumps(data: Any) -> str:
        import json

        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(data)

    @staticmethod
    def _loads_or_text(text: str) -> Any:
        import json

        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return text
