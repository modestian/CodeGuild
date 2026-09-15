"""Git Worktree 操作封装。

对应需求：FR-GIT-01/02（每任务独立 worktree/task-Tn 与 branch/agent-Tn；并行 Agent 不共享工作目录）。
"""
from __future__ import annotations

from pathlib import Path

from app.tools.common import run_host_git


async def repo_toplevel(path: Path) -> Path | None:
    """返回包含 path 的仓库根目录（path 不在任何仓库内时为 None）。"""
    if not path.exists() or not path.is_dir():
        return None
    code, out, _ = await run_host_git(path, ["rev-parse", "--show-toplevel"])
    if code != 0 or not out.strip():
        return None
    try:
        return Path(out.strip().splitlines()[0]).resolve()
    except (OSError, ValueError):
        return None


async def is_git_repo(path: Path) -> bool:
    """path 本身是否为 Git 仓库根目录（嵌套在外层仓库内的子目录不算）。

    不能用 `rev-parse --is-inside-work-tree`：它对嵌套子目录同样返回
    true，会导致 git init / add / commit 错误地落到外层仓库。
    """
    top = await repo_toplevel(path)
    return top is not None and top == path.resolve()


async def head_branch(path: Path) -> str:
    code, out, _ = await run_host_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if code == 0 else ""


async def has_commits(path: Path) -> bool:
    code, _, _ = await run_host_git(path, ["rev-parse", "--verify", "HEAD"])
    return code == 0


async def add_worktree(repo: Path, worktree_path: Path, branch: str, base: str | None = None) -> None:
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add", "-b", branch, str(worktree_path)]
    if base:
        args.append(base)
    code, out, err = await run_host_git(repo, args, timeout=120)
    if code != 0:
        raise RuntimeError(f"git worktree add 失败: {(err or out).strip()[:500]}")


async def remove_worktree(repo: Path, worktree_path: Path, force: bool = True) -> None:
    args = ["worktree", "remove", str(worktree_path)]
    if force:
        args.append("--force")
    code, out, err = await run_host_git(repo, args, timeout=120)
    if code != 0:
        await run_host_git(repo, ["worktree", "prune"])


async def list_worktrees(repo: Path) -> list[dict[str, str]]:
    code, out, err = await run_host_git(repo, ["worktree", "list", "--porcelain"])
    if code != 0:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries
