"""FastAPI 应用入口。

启动：uvicorn app.main:create_app --factory
或：codeguild serve
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import approvals, artifacts, projects, runs
from app.config import get_settings
from app.services.app_context import AppContext
from app.services.run_manager import RunManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ctx = AppContext(settings)
    await ctx.init()
    app.state.ctx = ctx
    app.state.run_manager = RunManager(ctx)
    logging.getLogger("copilot").info("应用启动完成：%s", settings.app_name)
    try:
        yield
    finally:
        await ctx.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="CodeGuild — 面向真实代码仓库的多 Agent 软件开发平台（LangGraph + Agent Harness + Code RAG）",
        version="0.1.0",
        lifespan=lifespan,
    )
    # 前端（Vite dev server / Tauri / 任意本地界面）跨域访问（localhost 工具）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(approvals.router)
    app.include_router(artifacts.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    # 生产模式：web/dist 构建产物存在时托管前端（SPA 回退：非 API 路径一律返回 index.html，
    # 支持 /run/xxx 等前端路由直接访问与刷新）
    dist = (Path(__file__).resolve().parent.parent / "web" / "dist").resolve()
    if dist.is_dir():
        from fastapi.responses import FileResponse

        index_html = dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):  # noqa: ANN202
            # 真实静态文件（assets 等）直接返回，其余回退 index.html 交给前端路由
            if full_path:
                candidate = (dist / full_path).resolve()
                if candidate.is_file() and candidate.is_relative_to(dist):
                    return FileResponse(candidate)
            # index.html 不做强缓存：前端重新构建后普通刷新即可拿到最新 bundle（避免新旧混用）
            return FileResponse(index_html, headers={"Cache-Control": "no-cache"})

    return app
