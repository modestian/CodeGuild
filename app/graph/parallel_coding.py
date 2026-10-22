"""并行 Coding 的纯调度与 Worker 状态边界。"""
from __future__ import annotations

import copy
import hashlib

from app.schemas.state import TaskRecord, TaskStatus


def _normalized_targets(task: TaskRecord) -> set[str]:
    return {
        path.strip().replace("\\", "/").casefold()
        for path in task.target_files
        if path and path.strip()
    }


def select_parallel_batch(
    tasks: list[TaskRecord], ordered_ready: list[str], limit: int
) -> list[str]:
    """按就绪顺序选择无已知文件冲突的有界任务批次。"""
    by_id = {task.id: task for task in tasks}
    capacity = max(1, int(limit))
    selected: list[str] = []
    claimed_files: set[str] = set()
    for task_id in ordered_ready:
        task = by_id.get(task_id)
        if task is None or task.status != TaskStatus.READY:
            continue
        targets = _normalized_targets(task)
        if targets and targets & claimed_files:
            continue
        selected.append(task_id)
        claimed_files.update(targets)
        if len(selected) >= capacity:
            break
    return selected


def stable_batch_id(run_id: str, task_ids: list[str], tasks: list[TaskRecord]) -> str:
    """用任务顺序和尝试次数生成 replay 稳定、retry 可区分的批次 ID。"""
    attempts = {task.id: task.attempts for task in tasks}
    source = "|".join(
        [run_id, *(f"{task_id}:{attempts.get(task_id, 0)}" for task_id in task_ids)]
    )
    return f"batch-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"


def make_worker_state(
    state: dict,
    *,
    task_id: str,
    batch_id: str,
    workspace_path: str,
    branch: str,
) -> dict:
    """复制父状态并替换所有会被 Coding SubGraph 修改的任务级字段。"""
    worker = copy.deepcopy(state)
    worker.update(
        {
            "active_task_id": task_id,
            "active_batch_id": batch_id,
            "workspace_path": workspace_path,
            "branch": branch,
            "changed_files": [],
            "validation": {},
            "plan": {},
            "plan_recorded": False,
            "scratch": {"batch_id": batch_id},
        }
    )
    return worker


def task_result_from_state(worker_state: dict) -> dict:
    """把完整 Worker 状态收窄为父图唯一允许合并的任务结果。"""
    scratch = worker_state.get("scratch") or {}
    coding_result = scratch.get("coding_result") or {}
    validation = dict(worker_state.get("validation") or {})
    task_id = str(worker_state.get("active_task_id") or "")
    task = next(
        (
            dict(item)
            for item in (worker_state.get("task_dag") or [])
            if isinstance(item, dict) and str(item.get("id") or "") == task_id
        ),
        {},
    )
    coding_done = coding_result.get("status") == "done"
    status = "done" if coding_done and validation.get("passed") else "failed"
    error = (
        str(coding_result.get("notes") or "")
        or str(validation.get("reason") or "")
        or str(validation.get("error") or "")
        or str(scratch.get("coding_error") or "")
    )
    return {
        "batch_id": str(scratch.get("batch_id") or worker_state.get("active_batch_id") or ""),
        "task_id": task_id,
        "status": status,
        "summary": str(coding_result.get("summary") or ""),
        "error": error,
        "changed_files": copy.deepcopy(worker_state.get("changed_files") or []),
        "validation": validation,
        "task": task,
    }
