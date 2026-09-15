"""数据库模型（PostgreSQL / SQLite 兼容）。

表：users / projects / runs / tasks / agent_runs / tool_runs / checkpoints / reviews / approvals /
guidance / run_events
对应需求：6.4 节数据需求、FR-OBS-02、FR-HITL-06、6.7 数据安全（留痕可审计）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    repo_path: Mapped[str] = mapped_column(String(1024))
    default_branch: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    current_agent: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(String(32), default="mvp")
    # 审批模式：auto（仅高风险审批）| interactive（关键操作逐步确认，FR-HITL 增强）
    approval_mode: Mapped[str] = mapped_column(String(16), default="auto")
    branch: Mapped[str] = mapped_column(String(256), default="")
    workspace_path: Mapped[str] = mapped_column(String(1024), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("run_id", "task_id", name="uq_task_run_taskid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    assigned_agent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="high")
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="running")
    model: Mapped[str] = mapped_column(String(128), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(64), default="")
    tool: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    decision: Mapped[str] = mapped_column(String(16), default="execute")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class CheckpointMeta(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    node: Mapped[str] = mapped_column(String(128), default="")
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    current_agent: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(64), default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    """人工审批记录（FR-HITL-06：审批留痕、可查询审计）。

    scope：once（仅批准本次调用，交互模式下每次重新询问）| always（批准后本次运行内免问）。
    consumed：一次性批准是否已被工具调用消费（消费后再次调用需重新审批）。
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(64), default="")
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(16), default="HIGH")
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/approved/rejected
    scope: Mapped[str] = mapped_column(String(16), default="once")  # once | always
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_by: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GuidanceRow(Base):
    """运行中人工补充要求（追加需求注入 Agent 执行循环，HITL 增强）。"""

    __tablename__ = "guidance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="user")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | consumed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunEventRow(Base):
    """事件持久化（SSE 断线重放）。"""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(64), index=True)
    agent: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
