"""Projects API（IR-01：POST /projects）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_ctx
from app.services.app_context import AppContext
from app.storage import repositories as repo

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    repo_path: str = Field(description="本地 Git 仓库路径")
    default_branch: Optional[str] = Field(default=None, description="基线分支（缺省为当前 HEAD）")
    init_if_needed: bool = Field(
        default=False, description="路径不是 Git 仓库/尚无提交时，自动初始化并创建基线提交"
    )


class ProjectOut(BaseModel):
    id: str
    name: str
    repo_path: str
    default_branch: str


@router.post("", response_model=ProjectOut)
async def create_project(payload: ProjectCreate, ctx: AppContext = Depends(get_ctx)) -> ProjectOut:
    ok, reason = await ctx.workspaces.validate_repo(payload.repo_path)
    if not ok and payload.init_if_needed:
        # 导入普通项目文件夹：自动 git init + 基线提交，使其具备创建 worktree 的条件
        ok, reason = await ctx.workspaces.ensure_repo_ready(payload.repo_path)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    async with ctx.database.session() as session:
        project = await repo.create_project(
            session, name=payload.name, repo_path=payload.repo_path, default_branch=payload.default_branch or ""
        )
    return ProjectOut(
        id=project.id, name=project.name, repo_path=project.repo_path, default_branch=project.default_branch
    )


@router.get("")
async def list_projects(ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        projects = await repo.list_projects(session)
    return {"projects": [ProjectOut.model_validate(p, from_attributes=True) for p in projects]}


@router.get("/{project_id}")
async def get_project(project_id: str, ctx: AppContext = Depends(get_ctx)):
    async with ctx.database.session() as session:
        project = await repo.get_project(session, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        runs = await repo.list_runs(session, project_id)
    return {
        "project": ProjectOut.model_validate(project, from_attributes=True),
        "runs": [
            {"id": r.id, "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in runs
        ],
    }
