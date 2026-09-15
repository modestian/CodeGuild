"""FastAPI 依赖：从 application state 获取 AppContext / RunManager。"""
from __future__ import annotations

from fastapi import Request

from app.services.app_context import AppContext
from app.services.run_manager import RunManager


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager
