"""Symbol Search：按符号名（class / function / method）查找定义。

对应需求：FR-RAG-05（Symbol Search）、FR-TOOL-03（read_symbol）。
MVP 采用正则符号提取（Python / JS / TS）；V3 升级 tree-sitter AST。
"""
from __future__ import annotations

import re
from pathlib import Path

# 语言 → 符号定义模式（kind, 捕获符号名的组号）
_PY_PATTERNS = [
    ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)")),
    ("variable", re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*")),
]

_JS_PATTERNS = [
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(")),
    ("variable", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")),
]


def language_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyi"}:
        return "python"
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return "javascript"
    return "unknown"


def extract_symbols(text: str, symbol: str) -> list[dict]:
    """在文本中查找符号定义，返回 [{line, kind, signature}]。"""
    results: list[dict] = []
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    for idx, line in enumerate(text.splitlines(), start=1):
        if symbol not in line:
            continue
        for kind, pattern in _PY_PATTERNS + _JS_PATTERNS:
            match = pattern.match(line)
            if match and word.search(line):
                results.append({"line": idx, "kind": kind, "signature": line.strip()[:300]})
                break
    return results
