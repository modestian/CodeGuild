"""工具集：Filesystem / Git / Execution / Retrieval / External / Control。

对应需求：FR-TOOL-01~07（五类工具统一注册）。
"""
from __future__ import annotations

from app.harness.registry import ToolRegistry


def register_all_tools(registry: ToolRegistry) -> None:
    """注册系统全部可用工具。"""
    from app.tools import control, filesystem, git, retrieval, shell

    filesystem.register(registry)
    git.register(registry)
    shell.register(registry)
    retrieval.register(registry)
    control.register(registry)
