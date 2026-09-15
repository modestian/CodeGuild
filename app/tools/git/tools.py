"""Git 工具：git_status / git_diff / git_log / git_branch / git_commit。

对应需求：FR-TOOL-04、FR-GIT-03、FR-POL-03（git_commit=HIGH）。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.harness.registry import FunctionTool, ToolContext, ToolError, ToolRegistry
from app.schemas.tool import RiskLevel, ToolCategory
from app.tools.common import run_host_git


class GitStatusInput(BaseModel):
    pass


class GitDiffInput(BaseModel):
    path: Optional[str] = Field(default=None, description="限定文件/目录")
    staged: bool = Field(default=False, description="仅查看已暂存变更")
    stat_only: bool = Field(default=False, description="仅统计摘要")
    max_chars: int = Field(default=40000, le=200000)


class GitLogInput(BaseModel):
    n: int = Field(default=10, ge=1, le=100)


class GitBranchInput(BaseModel):
    pass


class GitCommitInput(BaseModel):
    message: str = Field(description="提交信息")
    files: Optional[list[str]] = Field(default=None, description="限定文件列表，缺省为全部变更")


async def _status(args: GitStatusInput, ctx: ToolContext) -> dict[str, Any]:
    code, out, err = await run_host_git(ctx.workspace, ["status", "--porcelain=v1", "--branch"])
    if code != 0:
        raise ToolError(f"git status 失败: {err.strip()[:300]}")
    lines = out.splitlines()
    branch = lines[0].replace("##", "").strip() if lines else ""
    entries = [
        {"code": line[:2].strip(), "path": line[3:].strip()}
        for line in lines[1:]
        if line.strip()
    ]
    return {"branch": branch, "entries": entries, "clean": len(entries) == 0}


async def _mark_intent_to_add(ctx: ToolContext) -> None:
    """将未跟踪文件标记为 intent-to-add，使 git diff 能反映新文件。"""
    await run_host_git(ctx.workspace, ["add", "-A", "-N"])


async def _diff(args: GitDiffInput, ctx: ToolContext) -> dict[str, Any]:
    if not args.staged and not args.stat_only:
        await _mark_intent_to_add(ctx)
    cmd = ["diff"]
    if args.staged:
        cmd.append("--cached")
    cmd.append("HEAD")
    if args.stat_only:
        cmd.append("--stat")
    if args.path:
        cmd += ["--", args.path]
    code, out, err = await run_host_git(ctx.workspace, cmd)
    if code != 0:
        raise ToolError(f"git diff 失败: {err.strip()[:300]}")
    truncated = False
    if len(out) > args.max_chars:
        out = out[: args.max_chars] + f"\n... [diff 截断，共 {len(out)} 字符] ..."
        truncated = True
    return {"diff": out, "truncated": truncated}


async def _log(args: GitLogInput, ctx: ToolContext) -> dict[str, Any]:
    code, out, err = await run_host_git(
        ctx.workspace, ["log", f"-n{args.n}", "--pretty=format:%h|%an|%ad|%s", "--date=short"]
    )
    if code != 0:
        raise ToolError(f"git log 失败: {err.strip()[:300]}")
    commits = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]})
    return {"commits": commits}


async def _branch(args: GitBranchInput, ctx: ToolContext) -> dict[str, Any]:
    code, out, err = await run_host_git(ctx.workspace, ["branch", "--list", "--format=%(refname:short)|%(HEAD)"])
    if code != 0:
        raise ToolError(f"git branch 失败: {err.strip()[:300]}")
    current = ""
    branches: list[str] = []
    for line in out.splitlines():
        name, _, marker = line.partition("|")
        if marker.strip() == "*":
            current = name.strip()
        branches.append(name.strip())
    return {"current": current, "branches": branches}


async def _commit(args: GitCommitInput, ctx: ToolContext) -> dict[str, Any]:
    if args.files:
        code, out, err = await run_host_git(ctx.workspace, ["add", "--", *args.files])
    else:
        code, out, err = await run_host_git(ctx.workspace, ["add", "-A"])
    if code != 0:
        raise ToolError(f"git add 失败: {err.strip()[:300]}")
    code, out, err = await run_host_git(
        ctx.workspace,
        [
            "-c",
            "user.name=Multi-Agent Copilot",
            "-c",
            "user.email=copilot@local",
            "commit",
            "-m",
            args.message,
        ],
    )
    if code != 0:
        raise ToolError(f"git commit 失败: {(err or out).strip()[:500]}")
    code, sha, _ = await run_host_git(ctx.workspace, ["rev-parse", "--short", "HEAD"])
    return {"sha": sha.strip(), "message": args.message, "output": out.strip()[:500]}


def register(registry: ToolRegistry) -> None:
    registry.register(
        FunctionTool(
            name="git_status",
            description="查看 Git 工作区状态",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.LOW,
            input_model=GitStatusInput,
            handler=_status,
            timeout=20,
        )
    )
    registry.register(
        FunctionTool(
            name="git_diff",
            description="查看代码变更（默认对比 HEAD，包含未跟踪新文件）",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.LOW,
            input_model=GitDiffInput,
            handler=_diff,
            timeout=30,
        )
    )
    registry.register(
        FunctionTool(
            name="git_log",
            description="查看最近提交历史",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.LOW,
            input_model=GitLogInput,
            handler=_log,
            timeout=20,
        )
    )
    registry.register(
        FunctionTool(
            name="git_branch",
            description="查看当前分支与分支列表",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.LOW,
            input_model=GitBranchInput,
            handler=_branch,
            timeout=20,
        )
    )
    registry.register(
        FunctionTool(
            name="git_commit",
            description="暂存并提交变更（高风险操作，需人工审批）",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.HIGH,
            input_model=GitCommitInput,
            handler=_commit,
            timeout=60,
            required_permission="git_write",
        )
    )
