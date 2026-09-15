"""Retrieval 工具：retrieve_code / search_docs / search_history。

对应需求：FR-TOOL-06（Retrieval 工具集）、FR-RAG-07（检索结果以 Relevant Code Context
形式供给 Coding Agent）。MVP 提供 Lexical（BM25）基线，V2 增加 Dense / RRF / Reranker。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.harness.registry import FunctionTool, ToolContext, ToolError, ToolRegistry
from app.retrieval.bm25 import build_index
from app.schemas.tool import RiskLevel, ToolCategory
from app.tools.common import run_host_git


class RetrieveCodeInput(BaseModel):
    query: str = Field(description="检索查询（自然语言或代码关键词）")
    top_k: int = Field(default=8, ge=1, le=30)
    preview_lines: int = Field(default=30, ge=5, le=120)


class SearchDocsInput(BaseModel):
    query: str = Field(description="文档检索查询")
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHistoryInput(BaseModel):
    query: str = Field(description="在 Git 历史中搜索的内容（如函数名/关键字）")
    n: int = Field(default=10, ge=1, le=50)


async def _retrieve_code(args: RetrieveCodeInput, ctx: ToolContext) -> dict[str, Any]:
    index = build_index(ctx.workspace)
    results = index.search(args.query, top_k=args.top_k)
    chunks = []
    for scored in results:
        chunk = scored.chunk
        lines = chunk.text.splitlines()
        preview = "\n".join(lines[: args.preview_lines])
        if len(lines) > args.preview_lines:
            preview += f"\n... ({len(lines) - args.preview_lines} 行省略)"
        chunks.append(
            {
                "file": chunk.file,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "score": scored.score,
                "preview": preview[:2000],
            }
        )
    return {"query": args.query, "chunks": chunks, "count": len(chunks)}


async def _search_docs(args: SearchDocsInput, ctx: ToolContext) -> dict[str, Any]:
    index = build_index(
        ctx.workspace,
        include_exts={".md", ".rst", ".txt"},
        chunk_lines=80,
        max_files=120,
    )
    results = index.search(args.query, top_k=args.top_k)
    docs = [
        {
            "file": s.chunk.file,
            "lines": f"{s.chunk.start_line}-{s.chunk.end_line}",
            "score": s.score,
            "preview": s.chunk.text[:1500],
        }
        for s in results
    ]
    return {"query": args.query, "documents": docs, "count": len(docs)}


async def _search_history(args: SearchHistoryInput, ctx: ToolContext) -> dict[str, Any]:
    code, out, err = await run_host_git(
        ctx.workspace, ["log", f"-n{args.n}", "--oneline", f"-S{args.query}"]
    )
    if code != 0:
        raise ToolError(f"git log -S 失败: {err.strip()[:300]}")
    commits = []
    for line in out.splitlines():
        sha, _, message = line.partition(" ")
        commits.append({"sha": sha, "message": message.strip()})
    return {"query": args.query, "commits": commits, "count": len(commits)}


def register(registry: ToolRegistry) -> None:
    registry.register(
        FunctionTool(
            name="retrieve_code",
            description="代码检索：按查询返回相关代码块（BM25，V2 升级混合检索）",
            category=ToolCategory.RETRIEVAL,
            risk_level=RiskLevel.LOW,
            input_model=RetrieveCodeInput,
            handler=_retrieve_code,
            timeout=60,
        )
    )
    registry.register(
        FunctionTool(
            name="search_docs",
            description="文档检索：在 README / docs 中按查询返回相关段落",
            category=ToolCategory.RETRIEVAL,
            risk_level=RiskLevel.LOW,
            input_model=SearchDocsInput,
            handler=_search_docs,
            timeout=60,
        )
    )
    registry.register(
        FunctionTool(
            name="search_history",
            description="历史检索：在 Git 提交历史中搜索变更记录",
            category=ToolCategory.RETRIEVAL,
            risk_level=RiskLevel.LOW,
            input_model=SearchHistoryInput,
            handler=_search_history,
            timeout=60,
        )
    )
