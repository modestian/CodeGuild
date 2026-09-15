"""Policy Engine：工具执行前的校验链与风险决策。

对应需求：FR-POL-01~05、FR-HITL-02~04。

校验链（FR-POL-01）：
    Tool Call
      ↓ Schema Validation（由 ToolExecutor 调用 Pydantic 校验）
      ↓ Policy Validation（本模块：命令黑名单、参数规则）
      ↓ Permission Check（PermissionManager / Capability Profile）
      ↓ Risk Evaluation（LOW / MEDIUM / HIGH / CRITICAL）
      ↓ Execute / Approval / Reject
"""
from __future__ import annotations

import re

from app.config import Settings
from app.harness.permission import PermissionManager
from app.schemas.tool import PolicyAction, PolicyDecision, RiskLevel, ToolDef

# 危险命令黑名单（Policy Validation：即使模型生成也必须 Reject）
FORBIDDEN_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"rm\s+-rf\s+/(?:\s|$)", re.I),
    re.compile(r"rm\s+-rf\s+~", re.I),
    re.compile(r"mkfs(\.|\s)", re.I),
    re.compile(r"dd\s+if=.*of=/dev/", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\breboot\b", re.I),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"),  # fork bomb
    re.compile(r"git\s+push\s+.*--force", re.I),
    re.compile(r"\bformat\s+[a-z]:", re.I),
    re.compile(r"curl.*\|\s*(ba|z|da)?sh", re.I),
    re.compile(r"wget.*\|\s*(ba|z|da)?sh", re.I),
]

COMMAND_TOOLS = {"run_command", "run_test", "run_linter", "run_build"}

# 写入类工具（敏感路径检测对象：权限/配置/CI/密钥等关键文件）
SENSITIVE_WRITE_TOOLS = {"edit_file", "create_file", "apply_patch", "delete_file"}


class PolicyEngine:
    """策略引擎：权限、风险与审批决策（FR-POL-05：语义检测由 Guardrails 承载，V2）。"""

    def __init__(self, settings: Settings, permissions: PermissionManager):
        self.settings = settings
        self.permissions = permissions

    # ---------- Policy Validation ----------

    def validate(self, tool_def: ToolDef, args: dict) -> tuple[bool, str]:
        """策略校验（黑名单等），返回 (passed, reason)。"""
        if tool_def.name in COMMAND_TOOLS:
            command = ""
            for key in ("command", "cmd"):
                if isinstance(args.get(key), str):
                    command = args[key]
                    break
            if command:
                for pattern in FORBIDDEN_COMMAND_PATTERNS:
                    if pattern.search(command):
                        return False, f"命令命中策略黑名单: {pattern.pattern}"
        # 写入类工具不允许指向工作区外的路径（工具层还有二次防护）
        if tool_def.name in {"edit_file", "create_file"}:
            path = str(args.get("path", ""))
            if path.startswith(("/", "\\")) or ".." in path.split("/"):
                if not path.startswith("/workspace"):
                    return False, f"路径越界被策略拒绝: {path}"
        return True, "passed"

    # ---------- 敏感路径检测（FR-HITL 增强：关键文件强制人工审批） ----------

    @staticmethod
    def _write_paths(tool_name: str, args: dict) -> list[str]:
        """提取写入类工具影响的目标文件路径（apply_patch 从 unified diff 解析）。"""
        if tool_name == "apply_patch":
            patch = str(args.get("patch") or "")
            paths: list[str] = []
            for line in patch.splitlines():
                m = re.match(r"^\+\+\+\s+(?:b/)?(\S+)", line)
                if m and m.group(1) != "/dev/null":
                    paths.append(m.group(1))
            return paths
        path = str(args.get("path") or "")
        return [path] if path else []

    def sensitive_matches(self, tool_name: str, args: dict) -> list[str]:
        """返回命中敏感路径模式的文件列表（权限/配置/CI/密钥等关键文件）。"""
        if tool_name not in SENSITIVE_WRITE_TOOLS:
            return []
        patterns = [str(p).lower() for p in (self.settings.sensitive_path_patterns or []) if p]
        if not patterns:
            return []
        hits: list[str] = []
        for path in self._write_paths(tool_name, args):
            lowered = path.lower().replace("\\", "/")
            if any(p in lowered for p in patterns):
                hits.append(path)
        return hits

    # ---------- 决策评估 ----------

    def evaluate(self, agent: str, tool_def: ToolDef, args: dict) -> PolicyDecision:
        """输出明确决策：Execute / Approval / Reject（FR-POL-04）。"""
        # 1) Permission Check（最小权限，FR-CAP-05）
        allowed, reason = self.permissions.check(agent, tool_def.name)
        if not allowed:
            return PolicyDecision(action=PolicyAction.REJECT, reason=reason, risk_level=tool_def.risk_level)

        # 2) Policy Validation（黑名单 / 参数规则）
        passed, reason = self.validate(tool_def, args)
        if not passed:
            return PolicyDecision(action=PolicyAction.REJECT, reason=reason, risk_level=tool_def.risk_level)

        # 3) 敏感路径（权限/配置/CI/密钥等关键文件）：强制人工审批（同意/拒绝/额外需求）
        sensitive = self.sensitive_matches(tool_def.name, args)
        if sensitive:
            shown = ", ".join(sensitive[:5])
            return PolicyDecision(
                action=PolicyAction.APPROVAL,
                reason=f"涉及敏感文件（权限/配置/CI/密钥）需人工审批: {shown}",
                risk_level=RiskLevel.HIGH,
            )

        # 4) Risk Evaluation（FR-POL-02/03）
        risk = tool_def.risk_level
        if risk == RiskLevel.CRITICAL or tool_def.name in self.settings.forced_approval_tools:
            return PolicyDecision(
                action=PolicyAction.APPROVAL,
                reason=f"高风险/关键操作需强制人工审批（risk={risk.value}）",
                risk_level=risk,
            )

        if tool_def.name == "edit_file" and self.settings.require_approval_for_edit:
            return PolicyDecision(action=PolicyAction.APPROVAL, reason="edit_file 配置为需人工审批", risk_level=risk)
        if tool_def.name in {"delete_file", "apply_patch"} and self.settings.require_approval_for_delete:
            return PolicyDecision(action=PolicyAction.APPROVAL, reason=f"{tool_def.name} 配置为需人工审批", risk_level=risk)
        if tool_def.name == "git_commit" and self.settings.require_approval_for_commit:
            return PolicyDecision(action=PolicyAction.APPROVAL, reason="git_commit 配置为需人工审批", risk_level=risk)

        # 默认策略：
        # - LOW：直接执行（FR-HITL-02 自动允许）
        # - MEDIUM：直接执行（沙箱隔离 + 工作区限制）
        # - HIGH：默认转人工审批
        if risk == RiskLevel.HIGH:
            return PolicyDecision(
                action=PolicyAction.APPROVAL,
                reason=f"HIGH 风险操作转人工审批（risk={risk.value}）",
                risk_level=risk,
            )
        return PolicyDecision(action=PolicyAction.EXECUTE, reason="低风险操作，允许执行", risk_level=risk)
