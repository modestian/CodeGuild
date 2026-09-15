"""工具公共辅助：工作区路径安全、文本文件遍历、宿主 Git 调用。"""
from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Iterable, Optional

from app.harness.registry import ToolContext, ToolError

# 遍历时排除的目录
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "data",
}

# 文本文件扩展名（用于检索）
TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".kt", ".swift", ".scala", ".sql", ".sh",
    ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg",
    ".html", ".css", ".scss", ".vue", ".svelte", ".env.example", ".dockerfile", ".gitignore",
}


def resolve_workspace_path(ctx: ToolContext, path: str) -> Path:
    """解析相对于工作区的路径，阻止路径穿越（FR-SB-03 文件系统隔离）。"""
    workspace = ctx.workspace.resolve()
    raw = (path or ".").strip()
    if raw.startswith("/workspace"):
        raw = raw[len("/workspace"):] or "."
    candidate = (workspace / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ToolError(f"路径越界：{path} 不在工作区 {workspace} 内") from exc
    return candidate


def is_probably_text(path: Path) -> bool:
    if path.name.lower() in {"dockerfile", "makefile", "rakefile"}:
        return True
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return True
    if suffix == "" and path.is_file():
        try:
            chunk = path.read_bytes()[:1024]
            return b"\x00" not in chunk
        except OSError:
            return False
    return False


def iter_text_files(
    root: Path,
    pattern: Optional[str] = None,
    max_files: int = 3000,
) -> Iterable[Path]:
    """遍历工作区文本文件（排除 .git/node_modules 等）。"""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in sorted(filenames):
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue
            path = Path(dirpath) / name
            if not is_probably_text(path):
                continue
            yield path
            count += 1
            if count >= max_files:
                return


def read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"读取文件失败: {path.name}: {exc}") from exc
    if len(data) > max_bytes:
        data = data[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    # 统一换行：工作区文本一律按 LF 语义处理（避免 CRLF 双重转换）
    return text.replace("\r\n", "\n").replace("\r", "\n")


async def run_host_git(cwd: Path, args: list[str], timeout: float = 60.0) -> tuple[int, str, str]:
    """在宿主环境对工作区执行 Git 操作（工作区由 Harness 管理，非用户代码执行）。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOME"}
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ToolError("未找到 git 命令") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise ToolError(f"git 命令超时: git {' '.join(args)}") from exc
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def git_is_repo(path: Path) -> bool:
    if not path.exists():
        return False
    code, _, _ = await run_host_git(path, ["rev-parse", "--is-inside-work-tree"])
    return code == 0


async def git_head_branch(path: Path) -> str:
    code, out, _ = await run_host_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if code == 0 else ""
