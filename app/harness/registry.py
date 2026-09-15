"""Tool Registry：工具注册中心与工具基类。

对应需求：FR-TOOL-01（ToolRegistry 统一注册五类工具）、FR-TOOL-02（工具定义规范）。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel

from app.config import Settings
from app.harness.session import RuntimeSession
from app.schemas.tool import RiskLevel, ToolCategory, ToolDef, ToolResult


class ToolError(Exception):
    """工具执行失败（业务级错误，将转换为 ToolResult.ok=False）。"""


@dataclass
class ToolContext:
    """工具执行上下文：工作区、沙箱、会话等。"""

    run_id: str
    project_id: str
    agent: str
    workspace: Path
    session: RuntimeSession
    settings: Settings
    sandbox: Any = None  # SandboxManager（避免循环导入）
    artifacts_dir: Optional[Path] = None
    emit: Optional[Callable[[str, str, dict], None]] = None  # (type, message, data)


class BaseTool(ABC):
    """工具基类。"""

    def __init__(self, defn: ToolDef):
        self.defn = defn

    @property
    def name(self) -> str:
        return self.defn.name

    @abstractmethod
    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:  # pragma: no cover
        ...


class FunctionTool(BaseTool):
    """函数式工具：input_model 做 Schema 校验，handler 返回结构化 data。"""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        category: ToolCategory,
        risk_level: RiskLevel,
        input_model: type[BaseModel],
        handler: Callable[[BaseModel, ToolContext], Awaitable[Any]],
        output_model: Optional[type[BaseModel]] = None,
        timeout: float = 30.0,
        required_permission: Optional[str] = None,
    ):
        self.input_model = input_model
        self.handler = handler
        self.output_model = output_model
        defn = ToolDef(
            name=name,
            description=description,
            category=category,
            input_schema=input_model.model_json_schema(),
            output_schema=output_model.model_json_schema() if output_model else {},
            risk_level=risk_level,
            timeout=timeout,
            required_permission=required_permission,
        )
        super().__init__(defn)

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        validated = self.input_model.model_validate(args)
        started = time.perf_counter()
        data = await self.handler(validated, ctx)
        duration = (time.perf_counter() - started) * 1000
        # 统一结果形态
        raw: Optional[str] = None
        payload: Any = data
        if isinstance(data, tuple) and len(data) == 2:
            payload, raw = data
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        return ToolResult(
            ok=True,
            data=payload,
            raw_output=raw,
            duration_ms=round(duration, 2),
            risk_level=self.defn.risk_level,
        )


class ToolRegistry:
    """统一注册系统可用工具（FR-TOOL-01）。"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def must_get(self, name: str) -> BaseTool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"未注册的工具: {name}")
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all_defs(self) -> list[ToolDef]:
        return [t.defn for t in self._tools.values()]

    def defs_for(self, tool_names: list[str]) -> list[ToolDef]:
        return [self._tools[n].defn for n in tool_names if n in self._tools]

    def by_category(self, category: ToolCategory) -> list[ToolDef]:
        return [t.defn for t in self._tools.values() if t.defn.category == category]
