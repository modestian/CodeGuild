"""Artifacts API（运行产出物查看：需求 / 架构 / 测试 / 审查 / 最终报告）。

产出物由各 Agent 通过 AppContext.save_artifact 持久化到
data/artifacts/{run_id}/{name}.json（大产物引用制，FR-STATE-03）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ctx
from app.services.app_context import AppContext
from app.storage import repositories as repo

router = APIRouter(tags=["artifacts"])

# 已知产出物清单（顺序即前端展示顺序；白名单亦用于防路径穿越）
ARTIFACT_SPECS: list[dict[str, str]] = [
    {"name": "requirements", "title": "需求分析", "agent": "product"},
    {"name": "architecture", "title": "架构设计", "agent": "architect"},
    {"name": "test_report", "title": "测试报告", "agent": "tester"},
    {"name": "review_report", "title": "审查报告", "agent": "reviewer"},
    {"name": "final_report", "title": "最终报告", "agent": "system"},
]
ARTIFACT_NAMES = {spec["name"] for spec in ARTIFACT_SPECS}


async def _ensure_run(run_id: str, ctx: AppContext) -> None:
    async with ctx.database.session() as session:
        run = await repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在")


@router.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str, ctx: AppContext = Depends(get_ctx)):
    """列出该运行的产出物元信息（不存在的不报错，标记 exists=false）。"""
    await _ensure_run(run_id, ctx)
    items = []
    for spec in ARTIFACT_SPECS:
        path = ctx.run_artifact_path(run_id, spec["name"])
        exists = path.is_file()
        stat = path.stat() if exists else None
        items.append(
            {
                **spec,
                "exists": exists,
                "size": stat.st_size if stat else 0,
                "modified_at": (
                    datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat() if stat else None
                ),
            }
        )
    return {"artifacts": items}


@router.get("/runs/{run_id}/artifacts/{name}")
async def get_artifact(run_id: str, name: str, ctx: AppContext = Depends(get_ctx)):
    """读取单个产出物 JSON 内容（name 白名单受限）。"""
    await _ensure_run(run_id, ctx)
    if name not in ARTIFACT_NAMES:
        raise HTTPException(status_code=404, detail=f"未知产出物: {name}")
    path = ctx.run_artifact_path(run_id, name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="产出物尚未生成")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"产出物解析失败: {exc}") from exc
    return {"name": name, "data": data}
