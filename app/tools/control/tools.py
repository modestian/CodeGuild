"""控制工具：update_plan。

对应需求：FR-CODE-04（制定 Plan 后再执行修改）：
Coding Agent 必须先用 update_plan 记录修改计划，随后才允许 edit_file / create_file / apply_patch
（由 ToolExecutor 强制执行该顺序）。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.harness.registry import FunctionTool, ToolContext, ToolRegistry
from app.schemas.artifacts import CodingPlan, PlanStep
from app.schemas.tool import RiskLevel, ToolCategory


class UpdatePlanInput(BaseModel):
    task_id: str = Field(default="", description="当前任务 id")
    approach: str = Field(description="总体修改思路")
    steps: list[str] = Field(default_factory=list, description="步骤列表")
    files_to_change: list[str] = Field(default_factory=list, description="计划修改的文件")
    test_strategy: str = Field(default="", description="验证策略")


async def _update_plan(args: UpdatePlanInput, ctx: ToolContext) -> dict[str, Any]:
    plan = CodingPlan(
        task_id=args.task_id or ctx.session.task_id,
        approach=args.approach,
        steps=[PlanStep(step=i + 1, description=s) for i, s in enumerate(args.steps)],
        files_to_change=list(args.files_to_change),
        test_strategy=args.test_strategy,
    )
    ctx.session.plan = plan.model_dump()
    if ctx.emit:
        ctx.emit("plan_updated", f"Plan recorded: {args.approach[:120]}", plan.model_dump())
    return {"recorded": True, "plan": plan.model_dump()}


def register(registry: ToolRegistry) -> None:
    registry.register(
        FunctionTool(
            name="update_plan",
            description="记录当前任务的修改计划（必须在执行任何文件修改前调用）",
            category=ToolCategory.CONTROL,
            risk_level=RiskLevel.LOW,
            input_model=UpdatePlanInput,
            handler=_update_plan,
            timeout=10,
        )
    )
