"""Execution 工具：run_command / run_test / run_linter / run_build。

对应需求：FR-TOOL-05、FR-SB-01（所有执行经由 SandboxManager）、NFR-SEC-01。
风险映射：run_test / run_linter / run_build = MEDIUM；run_command = HIGH。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.harness.registry import FunctionTool, ToolContext, ToolError, ToolRegistry
from app.schemas.tool import RiskLevel, ToolCategory


def workspace_has_pytest_config(workspace: Path) -> bool:
    """工作区是否自带 pytest 配置（自带时 pytest 配置搜索到此为止）。"""
    if (workspace / "pytest.ini").exists() or (workspace / "tox.ini").exists():
        return True
    setup_cfg = workspace / "setup.cfg"
    if setup_cfg.is_file():
        try:
            if "[tool:pytest]" in setup_cfg.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        try:
            if "[tool.pytest.ini_options]" in pyproject.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
    return False


def pytest_isolation_env(workspace: Path, command: str) -> dict[str, str]:
    """pytest 配置隔离：工作区无自有配置时，防止继承上层目录的 pytest 配置。

    背景：工作区（data/workspaces/...）嵌套在 Copilot 工程目录下时，pytest 会向上搜索并
    采用 Copilot 工程的 pyproject addopts（例如 -q），导致目标仓库测试输出被双 -q 吞掉。
    工作区若自带配置则不做任何处理（尊重目标仓库配置）。
    """
    if "pytest" not in command:
        return {}
    if workspace_has_pytest_config(workspace):
        return {}
    # 中和上层配置：addopts（避免 -q 叠加吞汇总行）、testpaths（避免限制收集范围）
    return {"PYTEST_ADDOPTS": "-o addopts= -o testpaths="}


class RunCommandInput(BaseModel):
    command: str = Field(description="要在沙箱内执行的命令")
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=1800)


class RunTestInput(BaseModel):
    command: Optional[str] = Field(default=None, description="自定义测试命令（缺省使用项目配置 TEST_COMMAND）")
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=1800)


class RunLinterInput(BaseModel):
    command: Optional[str] = Field(default=None, description="自定义 Lint 命令（缺省使用 LINT_COMMAND）")
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=1800)


class RunBuildInput(BaseModel):
    command: Optional[str] = Field(default=None, description="自定义构建命令（缺省使用 BUILD_COMMAND）")
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=1800)


async def _execute(
    ctx: ToolContext, command: str, timeout_seconds: Optional[int], kind: str
) -> tuple[dict[str, Any], str]:
    sandbox = ctx.sandbox
    if sandbox is None:
        raise ToolError("Sandbox 未初始化")
    if ctx.emit:
        ctx.emit("test_started" if kind == "test" else "tool_result", f"Running: {command}", {"command": command})
    extra_env = pytest_isolation_env(ctx.workspace, command)
    result = await sandbox.run(command, cwd=ctx.workspace, timeout=timeout_seconds, extra_env=extra_env)
    data = {
        "command": command,
        "kind": kind,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "duration_ms": result.duration_ms,
        "sandbox_mode": result.mode,
        "stdout": result.stdout[-60_000:],
        "stderr": result.stderr[-20_000:],
    }
    raw = f"$ {command}\n{result.stdout}\n{result.stderr}".strip()
    return data, raw


async def _run_command(args: RunCommandInput, ctx: ToolContext) -> tuple[dict[str, Any], str]:
    return await _execute(ctx, args.command, args.timeout_seconds, "command")


async def _run_test(args: RunTestInput, ctx: ToolContext) -> tuple[dict[str, Any], str]:
    command = (args.command or ctx.settings.test_command or "").strip()
    if not command:
        raise ToolError("未配置测试命令（TEST_COMMAND）")
    return await _execute(ctx, command, args.timeout_seconds, "test")


async def _run_linter(args: RunLinterInput, ctx: ToolContext) -> tuple[dict[str, Any], str]:
    command = (args.command or ctx.settings.lint_command or "").strip()
    if not command:
        return {"skipped": True, "reason": "未配置 Lint 命令（LINT_COMMAND 为空）", "kind": "lint"}, ""
    return await _execute(ctx, command, args.timeout_seconds, "lint")


async def _run_build(args: RunBuildInput, ctx: ToolContext) -> tuple[dict[str, Any], str]:
    command = (args.command or ctx.settings.build_command or "").strip()
    if not command:
        return {"skipped": True, "reason": "未配置构建命令（BUILD_COMMAND 为空）", "kind": "build"}, ""
    return await _execute(ctx, command, args.timeout_seconds, "build")


def register(registry: ToolRegistry) -> None:
    registry.register(
        FunctionTool(
            name="run_command",
            description="在隔离沙箱内执行任意命令（高风险）",
            category=ToolCategory.EXECUTION,
            risk_level=RiskLevel.HIGH,
            input_model=RunCommandInput,
            handler=_run_command,
            timeout=1800,
            required_permission="sandbox_execute",
        )
    )
    registry.register(
        FunctionTool(
            name="run_test",
            description="在隔离沙箱内运行测试（pytest 等）",
            category=ToolCategory.EXECUTION,
            risk_level=RiskLevel.MEDIUM,
            input_model=RunTestInput,
            handler=_run_test,
            timeout=1800,
            required_permission="sandbox_execute",
        )
    )
    registry.register(
        FunctionTool(
            name="run_linter",
            description="在隔离沙箱内运行 Lint / 静态检查",
            category=ToolCategory.EXECUTION,
            risk_level=RiskLevel.MEDIUM,
            input_model=RunLinterInput,
            handler=_run_linter,
            timeout=900,
            required_permission="sandbox_execute",
        )
    )
    registry.register(
        FunctionTool(
            name="run_build",
            description="在隔离沙箱内执行构建",
            category=ToolCategory.EXECUTION,
            risk_level=RiskLevel.MEDIUM,
            input_model=RunBuildInput,
            handler=_run_build,
            timeout=1800,
            required_permission="sandbox_execute",
        )
    )
