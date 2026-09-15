"""Task DAG 与共享状态工具测试（FR-TASK-01~06、FR-ARCH-06）。"""
from __future__ import annotations

import pytest

from app.schemas.state import (
    DevState,
    TaskDAGError,
    TaskRecord,
    TaskStatus,
    compute_ready_tasks,
    empty_dev_state,
    propagate_blocking,
    topological_order,
    validate_task_dag,
)


def _task(tid: str, deps: list[str] | None = None, status: TaskStatus = TaskStatus.PENDING) -> TaskRecord:
    return TaskRecord(id=tid, title=f"Task {tid}", dependencies=deps or [], status=status)


class TestValidateDAG:
    def test_valid_dag(self):
        tasks = [_task("T1"), _task("T2", ["T1"]), _task("T3", ["T1"]), _task("T4", ["T2", "T3"])]
        validated = validate_task_dag(tasks)
        assert len(validated) == 4

    def test_duplicate_ids(self):
        with pytest.raises(TaskDAGError, match="重复"):
            validate_task_dag([_task("T1"), _task("T1")])

    def test_missing_dependency(self):
        with pytest.raises(TaskDAGError, match="不存在的任务"):
            validate_task_dag([_task("T1", ["T9"])])

    def test_cycle_detected(self):
        with pytest.raises(TaskDAGError, match="循环依赖"):
            validate_task_dag([_task("T1", ["T2"]), _task("T2", ["T1"])])

    def test_self_dependency(self):
        with pytest.raises(TaskDAGError):
            validate_task_dag([_task("T1", ["T1"])])


class TestReadyAndBlocking:
    def test_ready_tasks(self):
        tasks = [_task("T1"), _task("T2", ["T1"]), _task("T3", ["T1"])]
        assert compute_ready_tasks(tasks) == ["T1"]

    def test_ready_after_completion(self):
        tasks = [_task("T1", status=TaskStatus.COMPLETED), _task("T2", ["T1"])]
        assert compute_ready_tasks(tasks) == ["T2"]

    def test_blocking_propagation(self):
        tasks = [
            _task("T1", status=TaskStatus.FAILED),
            _task("T2", ["T1"]),
            _task("T3", ["T2"]),
        ]
        propagate_blocking(tasks)
        assert tasks[1].status == TaskStatus.BLOCKED
        assert tasks[2].status == TaskStatus.BLOCKED

    def test_topological_order(self):
        tasks = [_task("T4", ["T2", "T3"]), _task("T2", ["T1"]), _task("T3", ["T1"]), _task("T1")]
        order = topological_order(tasks)
        assert order.index("T1") < order.index("T2") < order.index("T4")
        assert order.index("T1") < order.index("T3") < order.index("T4")


class TestDevState:
    def test_empty_state_fields(self):
        state = empty_dev_state("p1", "r1", "需求")
        for key in (
            "project_id", "user_request", "requirements", "architecture", "task_dag",
            "ready_tasks", "current_tasks", "completed_tasks", "changed_files", "commits",
            "test_results", "review_results", "current_agent", "iteration", "retry_count",
            "errors", "run_status",
        ):
            assert key in state
        assert state["run_status"] == "created"
