"""WorkspaceManager：运行工作区生命周期（创建 / 差异 / 提交 / 清理）。

对应需求：FR-GIT-01/02（工作区隔离、独立分支）、P7 Safe Execution。
每个 Run 从项目仓库创建独立 git worktree 与 branch（agent/run-<id>），
在获得人工审批前不触碰用户原始仓库工作区。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.config import Settings
from app.tools.common import run_host_git
from app.workspace import worktree


class WorkspaceError(RuntimeError):
    pass


class WorkspaceInfo(BaseModel):
    path: str
    branch: str
    repo_path: str


def _slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower()
    return slug or "project"


class WorkspaceManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def validate_repo(self, repo_path: str) -> tuple[bool, str]:
        path = Path(repo_path).expanduser().resolve()
        if not path.exists():
            return False, f"仓库路径不存在: {path}"
        if not await worktree.is_git_repo(path):
            top = await worktree.repo_toplevel(path)
            if top is not None:
                return False, (
                    f"路径位于 Git 仓库内部（仓库根：{top}）；"
                    f"请导入仓库根目录，或勾选「自动初始化」在该文件夹内创建独立仓库: {path}"
                )
            return False, f"路径不是 Git 仓库: {path}"
        if not await worktree.has_commits(path):
            return False, f"仓库尚无任何提交（需要至少一个 commit 才能创建 worktree）: {path}"
        return True, "ok"

    async def ensure_repo_ready(self, repo_path: str) -> tuple[bool, str]:
        """导入非 Git 项目：必要时初始化仓库并创建基线提交。

        使用场景：用户导入普通项目文件夹（非 Git 或尚无提交）。
        文件夹若位于外层仓库内部，会初始化为独立的新仓库（不复用外层仓库）。
        基线提交作者取本机 git 配置（缺省 Local User）——必须非
        "Multi-Agent Copilot"，否则会被 _branch_base 当作 Agent 提交排除，
        导致提交后无法展示分支相对基线的 diff。
        """
        path = Path(repo_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            return False, f"路径不存在或不是文件夹: {path}"
        notes: list[str] = []
        if not await worktree.is_git_repo(path):
            code, out, err = await run_host_git(path, ["init", "-b", "main"], timeout=60)
            if code != 0:  # 兼容不支持 -b 的旧版 git
                code, out, err = await run_host_git(path, ["init"], timeout=60)
            if code != 0:
                return False, f"git init 失败: {(err or out).strip()[:300]}"
            notes.append("已初始化 Git 仓库")
        if not await worktree.has_commits(path):
            code, out, err = await run_host_git(path, ["add", "-A"], timeout=300)
            if code != 0:
                return False, f"git add 失败: {(err or out).strip()[:300]}"
            _, out, _ = await run_host_git(path, ["config", "user.name"])
            name = out.strip()
            _, out, _ = await run_host_git(path, ["config", "user.email"])
            email = out.strip()
            code, out, err = await run_host_git(
                path,
                [
                    "-c", f"user.name={name or 'Local User'}",
                    "-c", f"user.email={email or 'local@import'}",
                    "commit", "--allow-empty", "-m", "chore: 初始化仓库基线（系统导入）",
                ],
                timeout=300,
            )
            if code != 0:
                return False, f"创建基线提交失败: {(err or out).strip()[:300]}"
            notes.append("已创建基线提交")
        return True, "；".join(notes) if notes else "仓库已就绪"

    async def create_run_workspace(
        self, repo_path: str, project_name: str, run_id: str, base_branch: Optional[str] = None
    ) -> WorkspaceInfo:
        repo = Path(repo_path).expanduser().resolve()
        ok, reason = await self.validate_repo(str(repo))
        if not ok:
            raise WorkspaceError(reason)

        short = run_id[:8]
        branch = f"agent/run-{short}"
        # 必须解析为绝对路径：否则 git worktree add 会相对仓库目录解析，
        # 而下游 Agent/沙箱相对服务进程 CWD 解析，导致路径不一致。
        ws_path = (self.settings.workspaces_dir / f"{_slugify(project_name)}-run-{short}").resolve()

        # 清理同名残留 worktree（例如失败后重跑）
        if ws_path.exists():
            await worktree.remove_worktree(repo, ws_path, force=True)

        try:
            await worktree.add_worktree(repo, ws_path, branch, base=base_branch)
        except RuntimeError as exc:
            if "already exists" in str(exc):
                # 分支已存在：改用已存在分支创建 worktree
                code, out, err = await run_host_git(repo, ["worktree", "add", str(ws_path), branch], timeout=120)
                if code != 0:
                    raise WorkspaceError(f"创建 worktree 失败: {(err or out).strip()[:500]}") from exc
            else:
                raise WorkspaceError(str(exc)) from exc
        return WorkspaceInfo(path=str(ws_path), branch=branch, repo_path=str(repo))

    async def full_diff(self, workspace: Path, max_chars: int = 200_000, stat_only: bool = False) -> str:
        """完整变更 diff：

        1. 存在未提交变更（审查窗口期）→ `git diff HEAD`（含未跟踪新文件）；
        2. 工作区已干净（提交后）→ 回退展示本分支相对基线的 diff
           （基线 = 分支顶端往下的第一个非 Agent 提交），保证提交后仍可回顾变更。
        """
        if not stat_only:
            await run_host_git(workspace, ["add", "-A", "-N"])
        cmd = ["diff", "HEAD"]
        if stat_only:
            cmd.append("--stat")
        code, out, err = await run_host_git(workspace, cmd, timeout=60)
        if code != 0:
            raise WorkspaceError(f"git diff 失败: {err.strip()[:300]}")
        if out.strip():
            return self._truncate(out, max_chars)

        # 无未提交变更：展示分支累计变更（相对基线）
        base = await self._branch_base(workspace)
        if base:
            cmd2 = ["diff", base, "HEAD"]
            if stat_only:
                cmd2.append("--stat")
            code, out2, err2 = await run_host_git(workspace, cmd2, timeout=60)
            if code == 0:
                out = out2
        return self._truncate(out, max_chars)

    @staticmethod
    def _truncate(out: str, max_chars: int) -> str:
        if len(out) > max_chars:
            return out[:max_chars] + f"\n... [diff 截断，共 {len(out)} 字符] ..."
        return out

    async def _branch_base(self, workspace: Path) -> Optional[str]:
        """分支基线：从 HEAD 向下回溯，第一个非 Agent（Multi-Agent Copilot）提交。"""
        code, out, _ = await run_host_git(workspace, ["log", "-n", "200", "--format=%H%x09%an", "HEAD"], timeout=30)
        if code != 0 or not out.strip():
            return None
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            sha, author = parts[0].strip(), parts[1].strip()
            if author != "Multi-Agent Copilot":
                return sha
        return None

    async def changed_files(self, workspace: Path) -> list[dict[str, str]]:
        code, out, err = await run_host_git(workspace, ["status", "--porcelain=v1"])
        if code != 0:
            raise WorkspaceError(f"git status 失败: {err.strip()[:300]}")
        files: list[dict[str, str]] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            code_field = line[:2].strip()
            path = line[3:].strip()
            if " -> " in path:  # rename
                path = path.split(" -> ", 1)[1]
            files.append({"code": code_field, "path": path})
        return files

    async def commit(self, workspace: Path, message: str, files: Optional[list[str]] = None) -> dict[str, str]:
        if files:
            code, out, err = await run_host_git(workspace, ["add", "--", *files], timeout=60)
        else:
            code, out, err = await run_host_git(workspace, ["add", "-A"], timeout=60)
        if code != 0:
            raise WorkspaceError(f"git add 失败: {err.strip()[:300]}")
        code, out, err = await run_host_git(
            workspace,
            ["-c", "user.name=Multi-Agent Copilot", "-c", "user.email=copilot@local", "commit", "-m", message],
            timeout=60,
        )
        if code != 0:
            raise WorkspaceError(f"git commit 失败: {(err or out).strip()[:500]}")
        code, sha, _ = await run_host_git(workspace, ["rev-parse", "--short", "HEAD"])
        return {"sha": sha.strip(), "message": message}

    async def cleanup(self, repo_path: str, workspace: Path) -> None:
        repo = Path(repo_path).expanduser().resolve()
        await worktree.remove_worktree(repo, workspace, force=True)
