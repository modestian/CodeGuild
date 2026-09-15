"""工具协议：Tool Definition / Tool Call / Tool Result / 风险等级 / 策略决策。

对应需求：FR-TOOL-02（name/description/input_schema/output_schema/risk_level/timeout/required_permission）、
FR-POL-02/03/04（风险四级分类、风险映射、决策输出）。
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def order(self) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}[self.value]


class ToolCategory(str, Enum):
    FILESYSTEM = "filesystem"
    GIT = "git"
    EXECUTION = "execution"
    RETRIEVAL = "retrieval"
    EXTERNAL = "external"
    CONTROL = "control"  # 内部控制工具（update_plan / finish）


class PolicyAction(str, Enum):
    EXECUTE = "execute"
    APPROVAL = "approval"
    REJECT = "reject"


class ToolDef(BaseModel):
    """工具定义（FR-TOOL-02）。"""

    name: str
    description: str
    category: ToolCategory
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    timeout: float = 30.0
    required_permission: Optional[str] = None


class ToolCall(BaseModel):
    """模型发起的一次工具调用。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具执行结果（结构化 data + 原始输出 raw_output）。"""

    ok: bool
    data: Any = None
    error: Optional[str] = None
    raw_output: Optional[str] = None
    duration_ms: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    decision: PolicyAction = PolicyAction.EXECUTE

    def brief(self, max_chars: int = 300) -> str:
        if self.ok:
            text = str(self.data)
            return text[:max_chars]
        return f"ERROR: {(self.error or '')[:max_chars]}"


class PolicyDecision(BaseModel):
    """Policy Engine 决策输出（FR-POL-04）：Execute / Approval / Reject。"""

    action: PolicyAction
    reason: str
    risk_level: RiskLevel = RiskLevel.LOW


class AgentDecision(BaseModel):
    """Agent 单步决策（FR-EXEC-01 Decision 分支）。

    decision=tool_call → 执行工具；decision=final → 结束循环并输出结构化结果。
    """

    decision: str = Field(description="tool_call | final")
    tool: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Optional[dict[str, Any]] = None
    rationale: str = ""
