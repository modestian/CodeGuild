"""仓储操作：项目 / 运行 / 任务 / 追踪 / 审批 / 事件的读写。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select, update

from app.schemas.events import RunEvent
from app.schemas.state import TaskRecord, TaskStatus
from app.storage.models import (
    AgentRun,
    Approval,
    CheckpointMeta,
    GuidanceRow,
    Project,
    Review,
    Run,
    RunEventRow,
    TaskRow,
    ToolRun,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# =========================================================
# Projects
# =========================================================


async def create_project(session, name: str, repo_path: str, default_branch: str = "") -> Project:
    project = Project(name=name, repo_path=repo_path, default_branch=default_branch)
    session.add(project)
    await session.flush()
    return project


async def get_project(session, project_id: str) -> Optional[Project]:
    return await session.get(Project, project_id)


async def list_projects(session) -> Sequence[Project]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


# =========================================================
# Runs
# =========================================================


async def create_run(session, project_id: str, request: str, mode: str = "mvp", approval_mode: str = "auto") -> Run:
    run = Run(project_id=project_id, request=request, mode=mode, approval_mode=approval_mode, status="created")
    session.add(run)
    await session.flush()
    return run


async def get_run(session, run_id: str) -> Optional[Run]:
    return await session.get(Run, run_id)


async def update_run(session, run_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    await session.execute(update(Run).where(Run.id == run_id).values(**fields))


async def list_runs(session, project_id: Optional[str] = None) -> Sequence[Run]:
    stmt = select(Run).order_by(Run.created_at.desc())
    if project_id:
        stmt = stmt.where(Run.project_id == project_id)
    result = await session.execute(stmt)
    return result.scalars().all()


# =========================================================
# Tasks
# =========================================================


async def create_tasks(session, run_id: str, tasks: list[TaskRecord]) -> None:
    for t in tasks:
        session.add(
            TaskRow(
                run_id=run_id,
                task_id=t.id,
                title=t.title,
                description=t.description,
                dependencies=list(t.dependencies),
                status=t.status.value,
                assigned_agent=t.assigned_agent,
                priority=t.priority,
                acceptance_criteria=list(t.acceptance_criteria),
                attempts=t.attempts,
                result_summary=t.result_summary,
                error=t.error,
            )
        )
    await session.flush()


async def upsert_task(session, run_id: str, task: TaskRecord) -> None:
    result = await session.execute(
        select(TaskRow).where(TaskRow.run_id == run_id, TaskRow.task_id == task.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        await create_tasks(session, run_id, [task])
        return
    row.title = task.title
    row.description = task.description
    row.dependencies = list(task.dependencies)
    row.status = task.status.value
    row.assigned_agent = task.assigned_agent
    row.priority = task.priority
    row.acceptance_criteria = list(task.acceptance_criteria)
    row.attempts = task.attempts
    row.result_summary = task.result_summary
    row.error = task.error
    row.updated_at = _now()


async def sync_tasks(session, run_id: str, tasks: list[TaskRecord]) -> None:
    """将 DevState 中的任务列表整体同步到 DB。"""
    for t in tasks:
        await upsert_task(session, run_id, t)


async def list_tasks(session, run_id: str) -> Sequence[TaskRow]:
    result = await session.execute(select(TaskRow).where(TaskRow.run_id == run_id).order_by(TaskRow.id))
    return result.scalars().all()


# =========================================================
# Agent / Tool 追踪（FR-OBS-02）
# =========================================================


async def start_agent_run(session, run_id: str, agent: str, task_id: str, model: str) -> int:
    row = AgentRun(run_id=run_id, agent=agent, task_id=task_id, model=model, status="running")
    session.add(row)
    await session.flush()
    return row.id


async def finish_agent_run(
    session,
    agent_run_id: int,
    *,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    steps: int = 0,
    tool_calls: int = 0,
    error: str = "",
) -> None:
    await session.execute(
        update(AgentRun)
        .where(AgentRun.id == agent_run_id)
        .values(
            status=status,
            finished_at=_now(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            steps=steps,
            tool_calls=tool_calls,
            error=error,
        )
    )


async def add_tool_run(
    session,
    run_id: str,
    agent: str,
    tool: str,
    arguments: dict[str, Any],
    ok: bool,
    duration_ms: float,
    risk_level: str,
    decision: str,
    error: str = "",
) -> None:
    session.add(
        ToolRun(
            run_id=run_id,
            agent=agent,
            tool=tool,
            arguments=arguments,
            ok=ok,
            duration_ms=duration_ms,
            risk_level=risk_level,
            decision=decision,
            error=error[:2000],
        )
    )


async def add_checkpoint_meta(session, run_id: str, node: str, iteration: int, current_agent: str) -> None:
    session.add(
        CheckpointMeta(run_id=run_id, node=node, iteration=iteration, current_agent=current_agent)
    )


# =========================================================
# Reviews / Approvals
# =========================================================


async def add_review(session, run_id: str, task_id: str, approved: bool, report: dict[str, Any]) -> None:
    session.add(Review(run_id=run_id, task_id=task_id, approved=approved, report=report))


async def list_reviews(session, run_id: str) -> Sequence[Review]:
    result = await session.execute(select(Review).where(Review.run_id == run_id).order_by(Review.id))
    return result.scalars().all()


async def create_approval_request(
    session, run_id: str, tool: str, arguments: dict[str, Any], risk_level: str, reason: str
) -> Approval:
    row = Approval(
        run_id=run_id,
        tool=tool,
        arguments=arguments,
        risk_level=risk_level,
        reason=reason,
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


async def find_approval_for_tool(session, run_id: str, tool: str) -> Optional[Approval]:
    """查找最近一条针对某工具的审批记录。"""
    result = await session.execute(
        select(Approval).where(Approval.run_id == run_id, Approval.tool == tool).order_by(Approval.id.desc())
    )
    return result.scalars().first()


async def decide_approval(
    session, approval_id: int, status: str, decided_by: str = "user", note: str = "", scope: str = ""
) -> None:
    values: dict[str, Any] = {"status": status, "decided_by": decided_by, "note": note, "decided_at": _now()}
    if scope:
        values["scope"] = scope
    await session.execute(update(Approval).where(Approval.id == approval_id).values(**values))


async def mark_approval_consumed(session, approval_id: int) -> None:
    """标记一次性审批已被工具调用消费（消费后同工具再次调用需重新审批）。"""
    await session.execute(update(Approval).where(Approval.id == approval_id).values(consumed=True))


# =========================================================
# Guidance（运行中人工补充要求）
# =========================================================


async def create_guidance(session, run_id: str, text: str, source: str = "user") -> GuidanceRow:
    row = GuidanceRow(run_id=run_id, text=text, source=source, status="pending")
    session.add(row)
    await session.flush()
    return row


async def list_guidance(session, run_id: str, status: Optional[str] = None) -> Sequence[GuidanceRow]:
    stmt = select(GuidanceRow).where(GuidanceRow.run_id == run_id)
    if status:
        stmt = stmt.where(GuidanceRow.status == status)
    result = await session.execute(stmt.order_by(GuidanceRow.id))
    return result.scalars().all()


async def consume_guidance(session, guidance_ids: list[int]) -> None:
    if not guidance_ids:
        return
    await session.execute(
        update(GuidanceRow)
        .where(GuidanceRow.id.in_(guidance_ids))
        .values(status="consumed", consumed_at=_now())
    )


async def list_approvals(session, run_id: str) -> Sequence[Approval]:
    result = await session.execute(select(Approval).where(Approval.run_id == run_id).order_by(Approval.id))
    return result.scalars().all()


# =========================================================
# Run Events
# =========================================================


async def add_event(session, event: RunEvent) -> None:
    session.add(
        RunEventRow(
            run_id=event.run_id,
            seq=event.seq,
            type=event.type.value,
            agent=event.agent,
            message=event.message,
            data=event.data,
            ts=event.ts,
        )
    )


async def list_events(session, run_id: str, after_seq: int = -1) -> Sequence[RunEventRow]:
    result = await session.execute(
        select(RunEventRow)
        .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
        .order_by(RunEventRow.seq)
    )
    return result.scalars().all()


async def next_event_seq(session, run_id: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(RunEventRow.seq), -1)).where(RunEventRow.run_id == run_id)
    )
    return int(result.scalar_one()) + 1


# =========================================================
# 指标聚合（FR-EVAL-08：Tokens / Cost / Tool Calls / Execution Time）
# =========================================================


async def aggregate_metrics(session, run_id: str) -> dict[str, Any]:
    agent_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cost_usd), 0.0),
                func.count(AgentRun.id),
            ).where(AgentRun.run_id == run_id)
        )
    ).one()
    tool_row = (
        await session.execute(
            select(func.count(ToolRun.id), func.coalesce(func.sum(ToolRun.duration_ms), 0.0)).where(
                ToolRun.run_id == run_id
            )
        )
    ).one()
    approval_row = (
        await session.execute(
            select(func.count(Approval.id)).where(Approval.run_id == run_id)
        )
    ).one()
    run = await get_run(session, run_id)
    exec_seconds = 0.0
    if run is not None:
        end = run.finished_at or _now()
        start = run.created_at
        if start is not None:
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            exec_seconds = max(0.0, (end - start).total_seconds())
    return {
        "input_tokens": int(agent_row[0]),
        "output_tokens": int(agent_row[1]),
        "cost_usd": round(float(agent_row[2]), 6),
        "agent_runs": int(agent_row[3]),
        "tool_calls": int(tool_row[0]),
        "tool_time_ms": round(float(tool_row[1]), 1),
        "approvals": int(approval_row[0]),
        "execution_seconds": round(exec_seconds, 1),
    }
