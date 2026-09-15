"""权限体系：Capability Profile 与 PermissionManager。

对应需求：FR-CAP-01~05（统一 Runtime + 差异化配置；Coding/Test/Reviewer 画像；最小权限执行）、
P6 Least Privilege、NFR-SEC-02。

验收要点：
- Reviewer 调用 edit_file 必须被拒绝
- Test / Reviewer 对工作区默认只读
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# 工作区写入类工具
WRITE_TOOLS = {"edit_file", "create_file", "apply_patch"}
# 需要 shell/执行能力的工具
SHELL_TOOLS = {"run_command", "run_test", "run_linter", "run_build"}
# 控制类工具（所有 agent 内部允许）
CONTROL_TOOLS = {"update_plan"}


class CapabilityProfile(BaseModel):
    """Agent 能力画像（FR-CAP-01）。"""

    name: str
    tools: list[str] = Field(default_factory=list)
    workspace: Literal["read_only", "read_write"] = "read_only"
    shell: Literal["none", "sandbox_only"] = "none"
    max_steps: int = 20
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    denied_tools: list[str] = Field(default_factory=list)
    model: Optional[str] = None


# =========================================================
# 默认画像（可配置，对应 FR-CAP-02/03/04 与设计方案第 13 节）
# =========================================================

PROFILES: dict[str, CapabilityProfile] = {
    "coder": CapabilityProfile(
        name="coder",
        tools=[
            "read_file",
            "list_files",
            "search_code",
            "grep",
            "read_symbol",
            "edit_file",
            "create_file",
            "apply_patch",
            "run_test",
            "git_status",
            "git_diff",
            "update_plan",
        ],
        workspace="read_write",
        shell="sandbox_only",
        max_steps=50,
    ),
    "tester": CapabilityProfile(
        name="tester",
        tools=["read_file", "run_test", "run_linter", "run_build"],
        workspace="read_only",
        shell="sandbox_only",
        max_steps=20,
        denied_tools=["edit_file", "create_file", "apply_patch"],
    ),
    "reviewer": CapabilityProfile(
        name="reviewer",
        tools=["read_file", "search_code", "git_diff", "run_test"],
        workspace="read_only",
        shell="sandbox_only",
        max_steps=15,
        denied_tools=["edit_file", "create_file", "apply_patch"],
    ),
    "product": CapabilityProfile(
        name="product",
        tools=["read_file", "list_files", "search_code"],
        workspace="read_only",
        shell="none",
        max_steps=15,
    ),
    "architect": CapabilityProfile(
        name="architect",
        tools=["read_file", "list_files", "search_code", "read_symbol"],
        workspace="read_only",
        shell="none",
        max_steps=20,
    ),
    "supervisor": CapabilityProfile(
        name="supervisor",
        tools=[],
        workspace="read_only",
        shell="none",
        max_steps=1,
    ),
    "researcher": CapabilityProfile(
        name="researcher",
        tools=[],
        workspace="read_only",
        shell="none",
        max_steps=10,
    ),
    # 只读分析师（query 意图：介绍/解释仓库，不修改任何文件）
    "analyst": CapabilityProfile(
        name="analyst",
        tools=["read_file", "list_files", "search_code", "grep", "read_symbol", "git_status", "git_diff"],
        workspace="read_only",
        shell="none",
        max_steps=30,
        denied_tools=["edit_file", "create_file", "apply_patch", "run_command", "run_test"],
    ),
    # 意图分类器（单次结构化输出，无工具）
    "intent_router": CapabilityProfile(
        name="intent_router",
        tools=[],
        workspace="read_only",
        shell="none",
        max_steps=1,
    ),
}


class PermissionManager:
    """权限检查：基于 Capability Profile 的最小权限校验。"""

    def __init__(self, profiles: Optional[dict[str, CapabilityProfile]] = None):
        self.profiles = profiles or PROFILES

    def get_profile(self, agent: str) -> CapabilityProfile:
        if agent not in self.profiles:
            raise KeyError(f"未知 Agent 画像: {agent}")
        return self.profiles[agent]

    def check(self, agent: str, tool_name: str) -> tuple[bool, str]:
        """返回 (allowed, reason)。"""
        profile = self.get_profile(agent)

        if tool_name in CONTROL_TOOLS:
            return True, "控制类工具"

        if tool_name in profile.denied_tools:
            return False, f"Agent {agent} 显式禁止使用工具 {tool_name}"

        if tool_name not in profile.tools:
            return False, f"工具 {tool_name} 不在 Agent {agent} 的能力画像中"

        if tool_name in WRITE_TOOLS and profile.workspace != "read_write":
            return False, f"Agent {agent} 工作区为只读，禁止写操作 {tool_name}"

        if tool_name in SHELL_TOOLS and profile.shell == "none":
            return False, f"Agent {agent} 不允许执行沙箱命令"

        return True, "允许"
