"""Filesystem 工具：list_files / read_file / search_code / grep / read_symbol /
edit_file / create_file / apply_patch。

对应需求：FR-TOOL-03、FR-CODE-01~05。
风险映射（FR-POL-03）：读类 LOW；edit_file/create_file/apply_patch MEDIUM。
"""
from __future__ import annotations

import fnmatch
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.harness.registry import FunctionTool, ToolContext, ToolError, ToolRegistry
from app.retrieval.symbol_search import extract_symbols
from app.schemas.tool import RiskLevel, ToolCategory
from app.tools.common import iter_text_files, read_text, resolve_workspace_path, run_host_git


# =========================================================
# 输入模型
# =========================================================


class ListFilesInput(BaseModel):
    path: str = Field(default=".", description="相对于工作区的目录")
    depth: int = Field(default=2, ge=1, le=6, description="递归深度")
    pattern: Optional[str] = Field(default=None, description="文件名 glob，如 *.py")
    max_entries: int = Field(default=400, le=2000)


class ReadFileInput(BaseModel):
    path: str = Field(description="相对于工作区的文件路径")
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)
    max_chars: int = Field(default=30000, le=120000)


class SearchCodeInput(BaseModel):
    query: str = Field(description="检索关键词或正则")
    path: str = Field(default=".", description="限定目录")
    is_regex: bool = False
    case_sensitive: bool = False
    include: Optional[str] = Field(default=None, description="文件名过滤 glob，如 *.py")
    max_results: int = Field(default=60, le=200)
    context_lines: int = Field(default=0, ge=0, le=5)


class GrepInput(BaseModel):
    pattern: str = Field(description="正则表达式")
    path: str = Field(default=".")
    include: Optional[str] = None
    context_lines: int = Field(default=1, ge=0, le=5)
    max_results: int = Field(default=60, le=200)


class ReadSymbolInput(BaseModel):
    symbol: str = Field(description="符号名（类/函数/方法/变量）")
    path: str = Field(default=".", description="限定目录")
    max_results: int = Field(default=20, le=50)


class EditFileInput(BaseModel):
    path: str = Field(description="相对于工作区的文件路径")
    old_string: str = Field(description="被替换的精确文本（需唯一）")
    new_string: str = Field(description="替换后的文本")
    replace_all: bool = False


class CreateFileInput(BaseModel):
    path: str
    content: str
    overwrite: bool = False


class ApplyPatchInput(BaseModel):
    patch: str = Field(description="统一 diff（unified diff）格式补丁")


# =========================================================
# 实现
# =========================================================


async def _list_files(args: ListFilesInput, ctx: ToolContext) -> dict[str, Any]:
    root = resolve_workspace_path(ctx, args.path)
    if not root.exists():
        raise ToolError(f"目录不存在: {args.path}")
    if root.is_file():
        raise ToolError(f"{args.path} 是文件，请使用 read_file")
    workspace = ctx.workspace.resolve()
    entries: list[str] = []
    truncated = False
    root_depth = len(root.parts)
    skip_dirs = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - root_depth
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        if depth >= args.depth - 1:
            dirnames[:] = []  # 剪枝：不再深入
        rel_dir = Path(dirpath)
        for name in sorted(filenames) + dirnames:
            if args.pattern and not fnmatch.fnmatch(name, args.pattern):
                continue
            entry = rel_dir / name
            try:
                rel = entry.relative_to(workspace).as_posix()
            except ValueError:
                continue
            entries.append(rel + ("/" if entry.is_dir() else ""))
            if len(entries) >= args.max_entries:
                truncated = True
                break
        if truncated:
            break
    return {"root": args.path, "entries": entries, "count": len(entries), "truncated": truncated}


async def _read_file(args: ReadFileInput, ctx: ToolContext) -> dict[str, Any]:
    path = resolve_workspace_path(ctx, args.path)
    if not path.is_file():
        raise ToolError(f"文件不存在: {args.path}")
    text = read_text(path)
    lines = text.splitlines()
    total_lines = len(lines)
    start = (args.start_line or 1) - 1
    end = args.end_line if args.end_line else total_lines
    selected = lines[start:end]
    content = "\n".join(f"{start + i + 1:>5} | {line}" for i, line in enumerate(selected))
    truncated = False
    if len(content) > args.max_chars:
        content = content[: args.max_chars] + f"\n... [截断，共 {total_lines} 行] ..."
        truncated = True
    return {
        "path": args.path,
        "start_line": start + 1,
        "end_line": min(end, total_lines),
        "total_lines": total_lines,
        "content": content,
        "truncated": truncated,
    }


def _search(ctx: ToolContext, root: Path, matcher: re.Pattern[str], args: Any) -> dict[str, Any]:
    workspace = ctx.workspace.resolve()
    matches: list[dict[str, Any]] = []
    scanned = 0
    truncated = False
    for file in iter_text_files(root, pattern=args.include):
        scanned += 1
        text = read_text(file, max_bytes=1_500_000)
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if matcher.search(line):
                rel = file.relative_to(workspace).as_posix()
                entry: dict[str, Any] = {"file": rel, "line": idx + 1, "text": line.strip()[:400]}
                if getattr(args, "context_lines", 0):
                    lo = max(0, idx - args.context_lines)
                    hi = min(len(lines), idx + args.context_lines + 1)
                    entry["context"] = [f"{lo + i + 1}: {lines[lo + i][:300]}" for i in range(hi - lo)]
                matches.append(entry)
                if len(matches) >= args.max_results:
                    truncated = True
                    return {"matches": matches, "scanned_files": scanned, "truncated": truncated}
    return {"matches": matches, "scanned_files": scanned, "truncated": truncated}


async def _search_code(args: SearchCodeInput, ctx: ToolContext) -> dict[str, Any]:
    root = resolve_workspace_path(ctx, args.path)
    pattern = args.query if args.is_regex else re.escape(args.query)
    flags = 0 if args.case_sensitive else re.IGNORECASE
    try:
        matcher = re.compile(pattern, flags)
    except re.error as exc:
        raise ToolError(f"正则表达式无效: {exc}") from exc
    result = _search(ctx, root if root.is_dir() else ctx.workspace, matcher, args)
    result["query"] = args.query
    return result


async def _grep(args: GrepInput, ctx: ToolContext) -> dict[str, Any]:
    root = resolve_workspace_path(ctx, args.path)
    try:
        matcher = re.compile(args.pattern)
    except re.error as exc:
        raise ToolError(f"正则表达式无效: {exc}") from exc
    result = _search(ctx, root if root.is_dir() else ctx.workspace, matcher, args)
    result["pattern"] = args.pattern
    return result


async def _read_symbol(args: ReadSymbolInput, ctx: ToolContext) -> dict[str, Any]:
    root = resolve_workspace_path(ctx, args.path)
    workspace = ctx.workspace.resolve()
    definitions: list[dict[str, Any]] = []
    for file in iter_text_files(root if root.is_dir() else ctx.workspace):
        if file.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = read_text(file, max_bytes=1_000_000)
        found = extract_symbols(text, args.symbol)
        if not found:
            continue
        lines = text.splitlines()
        for item in found:
            line_no = item["line"]
            snippet_end = min(len(lines), line_no + 24)
            snippet = "\n".join(lines[line_no - 1 : snippet_end])
            definitions.append(
                {
                    "file": file.relative_to(workspace).as_posix(),
                    "line": line_no,
                    "kind": item["kind"],
                    "signature": item["signature"],
                    "snippet": snippet,
                }
            )
            if len(definitions) >= args.max_results:
                return {"symbol": args.symbol, "definitions": definitions, "truncated": True}
    return {"symbol": args.symbol, "definitions": definitions, "truncated": False}


async def _edit_file(args: EditFileInput, ctx: ToolContext) -> dict[str, Any]:
    path = resolve_workspace_path(ctx, args.path)
    if not path.is_file():
        raise ToolError(f"文件不存在: {args.path}（如需新建请使用 create_file）")
    text = read_text(path)
    original = text
    count = text.count(args.old_string)
    if count == 0:
        raise ToolError(f"未找到待替换文本（old_string）于 {args.path}，请先 read_file 确认精确内容")
    if count > 1 and not args.replace_all:
        raise ToolError(f"old_string 在 {args.path} 中出现 {count} 次，不唯一；请扩大上下文或设置 replace_all=true")
    replaced = count if args.replace_all else 1
    text = text.replace(args.old_string, args.new_string) if args.replace_all else text.replace(args.old_string, args.new_string, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    rel = path.relative_to(ctx.workspace.resolve()).as_posix()
    ctx.session.changed_files[rel] = "edit"
    # 变更预览（首个变更块）
    preview = ""
    try:
        import difflib

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(), text.splitlines(), fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""
            )
        )
        preview = "\n".join(diff_lines[:40])
    except Exception:  # noqa: BLE001
        pass
    return {
        "path": rel,
        "replacements": replaced,
        "bytes_before": len(original),
        "bytes_after": len(text),
        "diff_preview": preview,
    }


async def _create_file(args: CreateFileInput, ctx: ToolContext) -> dict[str, Any]:
    path = resolve_workspace_path(ctx, args.path)
    if path.exists() and not args.overwrite:
        raise ToolError(f"文件已存在: {args.path}（如需覆盖请设置 overwrite=true）")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.content, encoding="utf-8", newline="\n")
    rel = path.relative_to(ctx.workspace.resolve()).as_posix()
    ctx.session.changed_files[rel] = "create" if not args.overwrite else "overwrite"
    return {"path": rel, "bytes": len(args.content), "created": True}


async def _apply_patch(args: ApplyPatchInput, ctx: ToolContext) -> dict[str, Any]:
    patch = args.patch.strip()
    if not patch:
        raise ToolError("补丁内容为空")
    if not (patch.startswith("diff ") or patch.startswith("--- ") or patch.startswith("diff --git")):
        raise ToolError("补丁必须为 unified diff 格式（以 diff --git 或 --- 开头）")
    # 解析受影响文件
    affected: list[str] = []
    for line in patch.splitlines():
        m = re.match(r"^\+\+\+\s+(?:b/)?(\S+)", line)
        if m and m.group(1) != "/dev/null":
            affected.append(m.group(1))
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8", newline="\n") as fh:
        fh.write(patch if patch.endswith("\n") else patch + "\n")
        patch_file = fh.name
    try:
        code, out, err = await run_host_git(ctx.workspace, ["apply", "--whitespace=nowarn", patch_file])
    finally:
        try:
            Path(patch_file).unlink(missing_ok=True)
        except OSError:
            pass
    if code != 0:
        raise ToolError(f"git apply 失败: {(err or out).strip()[:800]}")
    for rel in affected:
        ctx.session.changed_files[rel] = "patch"
    return {"applied": True, "files": affected, "output": (out or err).strip()[:500]}


# =========================================================
# 注册
# =========================================================


def register(registry: ToolRegistry) -> None:
    registry.register(
        FunctionTool(
            name="list_files",
            description="列出工作区目录结构（递归、受深度与数量限制）",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.LOW,
            input_model=ListFilesInput,
            handler=_list_files,
            timeout=20,
        )
    )
    registry.register(
        FunctionTool(
            name="read_file",
            description="读取工作区文件内容（带行号，支持行区间）",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.LOW,
            input_model=ReadFileInput,
            handler=_read_file,
            timeout=20,
        )
    )
    registry.register(
        FunctionTool(
            name="search_code",
            description="在工作区按关键词/正则检索代码，返回匹配位置",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.LOW,
            input_model=SearchCodeInput,
            handler=_search_code,
            timeout=30,
        )
    )
    registry.register(
        FunctionTool(
            name="grep",
            description="在工作区按正则搜索（grep 语义）",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.LOW,
            input_model=GrepInput,
            handler=_grep,
            timeout=30,
        )
    )
    registry.register(
        FunctionTool(
            name="read_symbol",
            description="按符号名（类/函数/方法）查找定义与代码片段",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.LOW,
            input_model=ReadSymbolInput,
            handler=_read_symbol,
            timeout=30,
        )
    )
    registry.register(
        FunctionTool(
            name="edit_file",
            description="对已存在文件做精确文本替换（old_string 必须唯一或开启 replace_all）",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.MEDIUM,
            input_model=EditFileInput,
            handler=_edit_file,
            timeout=30,
            required_permission="workspace_write",
        )
    )
    registry.register(
        FunctionTool(
            name="create_file",
            description="创建新文件（可写多行内容）",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.MEDIUM,
            input_model=CreateFileInput,
            handler=_create_file,
            timeout=30,
            required_permission="workspace_write",
        )
    )
    registry.register(
        FunctionTool(
            name="apply_patch",
            description="以 unified diff 补丁方式修改多个文件",
            category=ToolCategory.FILESYSTEM,
            risk_level=RiskLevel.MEDIUM,
            input_model=ApplyPatchInput,
            handler=_apply_patch,
            timeout=30,
            required_permission="workspace_write",
        )
    )
