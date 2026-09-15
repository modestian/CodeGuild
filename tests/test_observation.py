"""Observation Adapter 测试（FR-OBSA-01~05）。

- 8000 行 pytest 输出 → 结构化 status/passed/failed/failures
- 日志截断、敏感信息过滤、重复消除
"""
from __future__ import annotations

from app.harness.observation import ObservationAdapter
from app.schemas.tool import ToolResult

PYTEST_OUTPUT = """============================= test session starts =============================
collected 52 items

tests/test_auth.py ...F..                                               [ 25%]
tests/test_api.py ..........................                           [ 75%]
tests/test_models.py ............                                       [100%]

================================== FAILURES ===================================
___________________________ test_invalid_token ____________________________

    def test_invalid_token():
>       assert response.status_code == 401
E       assert 500 == 401

tests/test_auth.py:42: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_auth.py::test_invalid_token - assert 500 == 401
FAILED tests/test_auth.py::test_expired_token - assert 500 == 401
========================= 2 failed, 50 passed in 12.34s ========================
"""


def _result(raw: str, ok: bool = True, exit_code: int = 0) -> ToolResult:
    """模拟 run_test 工具结果：ok 表示命令执行是否成功，exit_code 反映测试是否通过。"""
    return ToolResult(
        ok=ok,
        data={"stdout": raw, "stderr": "", "exit_code": exit_code, "timed_out": False},
        raw_output=raw,
    )


class TestPytestParsing:
    def test_parse_summary(self):
        adapter = ObservationAdapter()
        obs = adapter.adapt("run_test", _result(PYTEST_OUTPUT, exit_code=1))
        assert obs["status"] == "failed"
        assert obs["passed"] is False
        assert obs["summary"]["total"] == 52
        assert obs["summary"]["passed"] == 50
        assert obs["summary"]["failed"] == 2
        assert len(obs["failures"]) == 2
        assert obs["failures"][0]["test"].startswith("tests/test_auth.py::test_invalid_token")

    def test_parse_passed(self):
        output = "...s\n===== 52 passed, 2 skipped in 3.21s ====="
        adapter = ObservationAdapter()
        obs = adapter.adapt("run_test", _result(output))
        assert obs["passed"] is True
        assert obs["summary"]["passed"] == 52
        assert obs["summary"]["skipped"] == 2

    def test_huge_output_truncated(self):
        huge = "\n".join(f"line {i}" for i in range(8000)) + "\n===== 3 failed, 127 passed in 30s ====="
        adapter = ObservationAdapter(max_chars=3000)
        obs = adapter.adapt("run_test", _result(huge, exit_code=1))
        assert obs.get("truncated") is True
        assert obs["summary"]["failed"] == 3
        assert len(obs["output"]) < 4000


class TestRedactionAndCompression:
    def test_secret_redacted(self):
        adapter = ObservationAdapter()
        text = "key sk-abcdefghijklmnopqrstuvwx and ghp_" + "a" * 30 + " end"
        redacted = adapter.redact(text)
        assert "sk-abcdef" not in redacted
        assert "ghp_" not in redacted
        assert "[REDACTED]" in redacted

    def test_api_key_assignment_redacted(self):
        adapter = ObservationAdapter()
        redacted = adapter.redact('api_key = "abcdef1234567890abcdef"')
        assert "[REDACTED]" in redacted
        assert "abcdef1234567890abcdef" not in redacted

    def test_dedupe(self):
        adapter = ObservationAdapter()
        text = "\n".join(["same"] * 50 + ["other"])
        compressed = adapter.compress(text)
        assert "same" not in compressed or compressed.count("same") <= 1
        assert "重复省略" in compressed

    def test_error_result_structured(self):
        adapter = ObservationAdapter()
        obs = adapter.adapt(
            "edit_file",
            ToolResult(ok=False, error="未找到待替换文本", raw_output="detail text"),
        )
        assert obs["status"] == "error"
        assert "未找到待替换文本" in obs["error"]
