"""BM25 词法检索（MVP 基线）。

对应需求：FR-RAG-01~07（MVP 提供 Lexical Retrieval 基础；V2 增加 Dense / RRF / Reranker）。
纯 Python 实现，对工作区文本文件分块（按行窗口），按 BM25 打分返回 Top-K。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.tools.common import iter_text_files, read_text

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")

# 代码检索常用停用词（保持轻量）
_STOPWORDS = {
    "the", "a", "an", "and", "or", "if", "else", "for", "in", "of", "to", "is",
    "def", "class", "return", "import", "from", "self", "none", "true", "false",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


@dataclass
class Chunk:
    file: str
    start_line: int
    end_line: int
    text: str
    tokens: Counter = field(default_factory=Counter)


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


class BM25Index:
    """轻量 BM25 索引（k1=1.5, b=0.75）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: list[Chunk] = []
        self.doc_freq: Counter = Counter()
        self.avg_len: float = 1.0

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self.chunks.extend(chunks)
        for chunk in chunks:
            for term in chunk.tokens:
                self.doc_freq[term] += 1
        if self.chunks:
            self.avg_len = sum(sum(c.tokens.values()) for c in self.chunks) / len(self.chunks)

    def search(self, query: str, top_k: int = 8) -> list[ScoredChunk]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        n = len(self.chunks)
        scored: list[ScoredChunk] = []
        for chunk in self.chunks:
            length = sum(chunk.tokens.values()) or 1
            score = 0.0
            for term in set(terms):
                tf = chunk.tokens.get(term, 0)
                if tf == 0:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                score += idf * tf * (self.k1 + 1) / denom
            if score > 0:
                scored.append(ScoredChunk(chunk=chunk, score=round(score, 4)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]


def build_index(
    workspace: Path,
    *,
    include_exts: set[str] | None = None,
    name_pattern: str | None = None,
    chunk_lines: int = 60,
    overlap: int = 10,
    max_files: int = 400,
    max_bytes_per_file: int = 300_000,
) -> BM25Index:
    """对工作区构建 BM25 索引。"""
    index = BM25Index()
    count = 0
    for file in iter_text_files(workspace, pattern=name_pattern, max_files=max_files):
        if include_exts and file.suffix.lower() not in include_exts:
            continue
        count += 1
        text = read_text(file, max_bytes=max_bytes_per_file)
        lines = text.splitlines()
        rel = file.relative_to(workspace.resolve()).as_posix()
        step = max(1, chunk_lines - overlap)
        for start in range(0, max(1, len(lines)), step):
            end = min(len(lines), start + chunk_lines)
            snippet = "\n".join(lines[start:end]).strip()
            if not snippet:
                continue
            index.add_chunks(
                [Chunk(file=rel, start_line=start + 1, end_line=end, text=snippet, tokens=Counter(tokenize(snippet)))]
            )
            if end >= len(lines):
                break
        if count >= max_files:
            break
    return index
