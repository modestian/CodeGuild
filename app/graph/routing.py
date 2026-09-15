"""共享状态与路由函数。

DevState 定义于 app.schemas.state；本模块提供图中的条件路由函数（Conditional Edge）。
"""
from __future__ import annotations

from app.schemas.state import DevState, TaskRecord, TaskStatus, empty_dev_state  # noqa: F401

# Main Graph：Supervisor 决策 → 节点映射
SUPERVISOR_ROUTES = {
    "product": "product",
    "architect": "architect",
    "development": "development",
    "final_review": "final_review",
    "human_approval": "human_approval",
    "commit": "commit",
    "end": "end",
}


def route_after_supervisor(state: dict) -> str:
    return state.get("route") or "end"


# Main Graph：意图路由（query 只读问答 | develop 开发闭环）
INTENT_ROUTES = {"query": "answer", "develop": "supervisor"}


def route_after_intent(state: dict) -> str:
    intent = state.get("request_intent") or "develop"
    return "answer" if intent == "query" else "supervisor"


# Coding SubGraph：验证后路由
CODING_ROUTES = {"repair": "execute", "finish": "end", "failed": "end"}


def route_after_validation(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("coding_route") or "failed"


# Development SubGraph 路由
DEV_ROUTES = {
    "code": "code_task",
    "test": "testing",
    "review": "review",
    "repair": "repair",
    "schedule": "scheduler",
    "done": "end",
    "blocked": "end",
}


def route_after_scheduler(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("dev_stage") or "blocked"


def route_after_finalize(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("finalize_route") or "blocked"


def route_after_repair(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("repair_route") or "blocked"


def route_after_testing(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("test_route") or "blocked"


def route_after_review(state: dict) -> str:
    scratch = state.get("scratch") or {}
    return scratch.get("review_route") or "blocked"


def is_terminal_status(state: dict) -> bool:
    return state.get("run_status") in {"completed", "rejected", "failed", "cancelled"}
