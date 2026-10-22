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


class TaskWorkspaceInfo(WorkspaceInfo):
    run_id: str
    batch_id: str
    task_id: str


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

    async def create_task_workspace(
        self,
        run_workspace: Path,
        run_branch: str,
        run_id: str,
        batch_id: str,
        task_id: str,
    ) -> TaskWorkspaceInfo:
        """为 Coding 任务创建或复用隔离 worktree；相同身份调用保持幂等。"""
        run_workspace = run_workspace.resolve()
        if not await worktree.is_git_repo(run_workspace):
            raise WorkspaceError(f"Run 工作区不是 Git 仓库根目录: {run_workspace}")

        root = self.settings.workspaces_dir.resolve()
        task_slug = _slugify(task_id)
        batch_slug = _slugify(batch_id)[:16]
        run_slug = _slugify(run_id)[:12]
        task_root = (root / f"{run_workspace.name}-tasks").resolve()
        ws_path = (task_root / f"{task_slug}-{batch_slug}").resolve()
        if not ws_path.is_relative_to(root):
            raise WorkspaceError(f"任务工作区越界: {ws_path}")

        # Git ref 不能同时存在 `agent/run-x` 和 `agent/run-x/...`，因此任务
        # 分支使用同级命名，而不是挂在 Run 分支 ref 下。
        branch = f"agent/task-{run_slug}-{task_slug}-{batch_slug}"
        if ws_path.exists():
            existing_branch = await worktree.head_branch(ws_path)
            if existing_branch == branch:
                return TaskWorkspaceInfo(
                    path=str(ws_path),
                    branch=branch,
                    repo_path=str(run_workspace),
                    run_id=run_id,
                    batch_id=batch_id,
                    task_id=task_id,
                )
            raise WorkspaceError(f"任务工作区已存在但分支不匹配: {ws_path} ({existing_branch})")

        try:
            await worktree.add_worktree(run_workspace, ws_path, branch, base=run_branch or "HEAD")
        except RuntimeError as exc:
            if "already exists" not in str(exc):
                raise WorkspaceError(str(exc)) from exc
            code, out, err = await run_host_git(
                run_workspace, ["worktree", "add", str(ws_path), branch], timeout=120
            )
            if code != 0:
                raise WorkspaceError(f"恢复任务 worktree 失败: {(err or out).strip()[:500]}") from exc

        return TaskWorkspaceInfo(
            path=str(ws_path),
            branch=branch,
            repo_path=str(run_workspace),
            run_id=run_id,
            batch_id=batch_id,
            task_id=task_id,
        )

    async def commit_task_workspace(
        self, task_workspace: Path, task_id: str, summary: str = ""
    ) -> dict[str, str]:
        """提交任务工作区；节点 replay 时复用已存在的任务提交。"""
        task_workspace = task_workspace.resolve()
        changed = await self.changed_files(task_workspace)
        message = f"feat({task_id}): {summary.strip() or 'complete coding task'}"
        if changed:
            await self.commit(task_workspace, message)
        code, sha, err = await run_host_git(task_workspace, ["rev-parse", "HEAD"])
        if code != 0 or not sha.strip():
            raise WorkspaceError(f"读取任务提交失败: {(err or sha).strip()[:300]}")
        return {"sha": sha.strip(), "message": message, "reused": str(not changed).lower()}

    async def integrate_task_commit(
        self, run_workspace: Path, commit_sha: str, task_id: str
    ) -> dict[str, object]:
        """将任务提交幂等地集成到 Run 分支，冲突时恢复干净状态。"""
        run_workspace = run_workspace.resolve()
        code, _, err = await run_host_git(
            run_workspace, ["cat-file", "-e", f"{commit_sha}^{{commit}}"]
        )
        if code != 0:
            raise WorkspaceError(f"任务 {task_id} 提交不存在: {(err or commit_sha).strip()[:300]}")

        if await worktree.commit_already_applied(run_workspace, commit_sha):
            return {
                "task_id": task_id,
                "commit_sha": commit_sha,
                "integrated": True,
                "already_integrated": True,
                "conflict": False,
                "conflict_files": [],
            }

        code, out, err = await run_host_git(
            run_workspace, ["cherry-pick", commit_sha], timeout=120
        )
        if code == 0:
            return {
                "task_id": task_id,
                "commit_sha": commit_sha,
                "integrated": True,
                "already_integrated": False,
                "conflict": False,
                "conflict_files": [],
            }

        _, conflicts, _ = await run_host_git(
            run_workspace, ["diff", "--name-only", "--diff-filter=U"]
        )
        await run_host_git(run_workspace, ["cherry-pick", "--abort"], timeout=60)
        return {
            "task_id": task_id,
            "commit_sha": commit_sha,
            "integrated": False,
            "already_integrated": False,
            "conflict": True,
            "conflict_files": [line.strip() for line in conflicts.splitlines() if line.strip()],
            "error": (err or out).strip()[:1000],
        }

    async def cleanup_task_workspace(self, run_workspace: Path, task_workspace: Path) -> None:
        await worktree.remove_worktree(run_workspace.resolve(), task_workspace.resolve(), force=True)

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

    async def commit(
        self,
        workspace: Path,
        message: str,
        files: Optional[list[str]] = None,
        *,
        allow_empty: bool = False,
    ) -> dict[str, str]:
        if files:
            code, out, err = await run_host_git(workspace, ["add", "--", *files], timeout=60)
        else:
            code, out, err = await run_host_git(workspace, ["add", "-A"], timeout=60)
        if code != 0:
            raise WorkspaceError(f"git add 失败: {err.strip()[:300]}")
        commit_args = [
            "-c", "user.name=Multi-Agent Copilot",
            "-c", "user.email=copilot@local",
            "commit",
        ]
        if allow_empty:
            commit_args.append("--allow-empty")
        commit_args.extend(["-m", message])
        code, out, err = await run_host_git(workspace, commit_args, timeout=60)
        if code != 0:
            raise WorkspaceError(f"git commit 失败: {(err or out).strip()[:500]}")
        code, sha, _ = await run_host_git(workspace, ["rev-parse", "--short", "HEAD"])
        return {"sha": sha.strip(), "message": message}

    async def cleanup(self, repo_path: str, workspace: Path) -> None:
        repo = Path(repo_path).expanduser().resolve()
        await worktree.remove_worktree(repo, workspace, force=True)
