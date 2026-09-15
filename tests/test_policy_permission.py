"""Policy Engine 与 Permission / Capability Profile 测试。

验收要点（需求报告 3.9/3.10）：
- Reviewer 调用 edit_file 必须被拒绝
- Test / Reviewer 对工作区默认只读
- 风险分级与决策输出（Execute / Approval / Reject）
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.harness.permission import PermissionManager
from app.harness.policy import PolicyEngine
from app.schemas.tool import PolicyAction, RiskLevel, ToolCategory, ToolDef


@pytest.fixture
def engine() -> PolicyEngine:
    settings = Settings(_env_file=None, llm_provider="mock")
    return PolicyEngine(settings, PermissionManager())


def _tool(name: str, risk: RiskLevel, category: ToolCategory = ToolCategory.FILESYSTEM) -> ToolDef:
    return ToolDef(name=name, description=name, category=category, risk_level=risk)


def _engine_with_git_tools() -> PolicyEngine:
    """高风险 Git 工具不在默认画像中，测试时显式授权以验证风险决策链。"""
    from app.harness.permission import CapabilityProfile

    settings = Settings(_env_file=None, llm_provider="mock")
    profiles = {
        "coder": CapabilityProfile(
            name="coder", tools=["git_commit", "git_push", "edit_file", "read_file"], workspace="read_write"
        )
    }
    return PolicyEngine(settings, PermissionManager(profiles))


class TestPermission:
    def test_reviewer_cannot_edit(self):
        pm = PermissionManager()
        allowed, reason = pm.check("reviewer", "edit_file")
        assert not allowed
        assert "禁止" in reason or "只读" in reason

    def test_reviewer_create_denied(self):
        pm = PermissionManager()
        allowed, _ = pm.check("reviewer", "create_file")
        assert not allowed

    def test_tester_read_only(self):
        pm = PermissionManager()
        allowed, _ = pm.check("tester", "edit_file")
        assert not allowed
        allowed, _ = pm.check("tester", "read_file")
        assert allowed

    def test_coder_can_edit(self):
        pm = PermissionManager()
        allowed, _ = pm.check("coder", "edit_file")
        assert allowed

    def test_product_no_shell(self):
        pm = PermissionManager()
        allowed, _ = pm.check("product", "run_test")
        assert not allowed

    def test_tool_not_in_profile(self):
        pm = PermissionManager()
        allowed, reason = pm.check("reviewer", "run_command")
        assert not allowed


class TestPolicyEngine:
    def test_low_risk_execute(self, engine: PolicyEngine):
        decision = engine.evaluate("coder", _tool("read_file", RiskLevel.LOW), {})
        assert decision.action == PolicyAction.EXECUTE

    def test_edit_file_medium_execute_by_default(self, engine: PolicyEngine):
        decision = engine.evaluate("coder", _tool("edit_file", RiskLevel.MEDIUM), {"path": "a.py"})
        assert decision.action == PolicyAction.EXECUTE

    def test_edit_file_approval_when_configured(self):
        settings = Settings(_env_file=None, llm_provider="mock", require_approval_for_edit=True)
        engine = PolicyEngine(settings, PermissionManager())
        decision = engine.evaluate("coder", _tool("edit_file", RiskLevel.MEDIUM), {"path": "a.py"})
        assert decision.action == PolicyAction.APPROVAL

    def test_high_risk_approval(self):
        engine = _engine_with_git_tools()
        decision = engine.evaluate("coder", _tool("git_commit", RiskLevel.HIGH, ToolCategory.GIT), {})
        assert decision.action == PolicyAction.APPROVAL

    def test_critical_approval(self):
        engine = _engine_with_git_tools()
        decision = engine.evaluate("coder", _tool("git_push", RiskLevel.CRITICAL, ToolCategory.GIT), {})
        assert decision.action == PolicyAction.APPROVAL

    def test_reviewer_edit_rejected(self, engine: PolicyEngine):
        decision = engine.evaluate("reviewer", _tool("edit_file", RiskLevel.MEDIUM), {"path": "a.py"})
        assert decision.action == PolicyAction.REJECT
        assert "拒绝" in decision.reason or "禁止" in decision.reason or "不在" in decision.reason

    def test_forbidden_command_rejected(self, engine: PolicyEngine):
        decision = engine.evaluate(
            "tester",
            _tool("run_test", RiskLevel.MEDIUM, ToolCategory.EXECUTION),
            {"command": "rm -rf / --no-preserve-root"},
        )
        assert decision.action == PolicyAction.REJECT

    def test_path_escape_rejected(self, engine: PolicyEngine):
        decision = engine.evaluate(
            "coder", _tool("edit_file", RiskLevel.MEDIUM), {"path": "../../etc/passwd"}
        )
        assert decision.action == PolicyAction.REJECT

    def test_sensitive_path_requires_approval(self, engine: PolicyEngine):
        """敏感文件（权限/配置/CI/密钥）命中即强制人工审批。"""
        for path in (".env", "docker/Dockerfile", ".github/workflows/ci.yml", "app/config.py", "certs/server.pem"):
            decision = engine.evaluate("coder", _tool("edit_file", RiskLevel.MEDIUM), {"path": path})
            assert decision.action == PolicyAction.APPROVAL, f"path={path} decision={decision.action}"

    def test_normal_path_not_escalated(self, engine: PolicyEngine):
        decision = engine.evaluate("coder", _tool("edit_file", RiskLevel.MEDIUM), {"path": "noteapp/core.py"})
        assert decision.action == PolicyAction.EXECUTE

    def test_apply_patch_sensitive_detected(self, engine: PolicyEngine):
        patch = (
            "diff --git a/.env b/.env\n"
            "--- a/.env\n"
            "+++ b/.env\n"
            "@@ -1 +1 @@\n"
            "-OLD=1\n"
            "+OLD=2\n"
        )
        decision = engine.evaluate("coder", _tool("apply_patch", RiskLevel.MEDIUM), {"patch": patch})
        assert decision.action == PolicyAction.APPROVAL
