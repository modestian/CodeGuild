"""并行 Coding 调度、Worker 隔离与 Development Graph 测试。"""
from __future__ import annotations

from app.graph.parallel_coding import (
    make_worker_state,
    select_parallel_batch,
    stable_batch_id,
    task_result_from_state,
)
from app.schemas.state import TaskRecord, TaskStatus, empty_dev_state


def _task(task_id: str, target_files: list[str] | None = None, attempts: int = 0) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        title=task_id,
        status=TaskStatus.READY,
        target_files=target_files or [],
        attempts=attempts,
    )


class TestParallelBatchSelection:
    def test_preserves_ready_order_and_respects_limit(self):
        tasks = [_task("T1"), _task("T2"), _task("T3")]

        assert select_parallel_batch(tasks, ["T3", "T1", "T2"], 2) == ["T3", "T1"]

    def test_serializes_known_overlapping_files_but_fills_batch(self):
        tasks = [
            _task("T1", ["app/api.py"]),
            _task("T2", ["app/api.py", "tests/test_api.py"]),
            _task("T3", ["app/model.py"]),
        ]

        assert select_parallel_batch(tasks, ["T1", "T2", "T3"], 2) == ["T1", "T3"]

    def test_non_positive_limit_falls_back_to_one(self):
        tasks = [_task("T1"), _task("T2")]

        assert select_parallel_batch(tasks, ["T1", "T2"], 0) == ["T1"]
        assert select_parallel_batch(tasks, ["T1", "T2"], -5) == ["T1"]

    def test_batch_id_is_stable_for_replay_and_changes_for_retry(self):
        tasks = [_task("T1", attempts=0), _task("T2", attempts=1)]
        first = stable_batch_id("run-1", ["T1", "T2"], tasks)

        assert stable_batch_id("run-1", ["T1", "T2"], tasks) == first
        assert stable_batch_id("run-1", ["T2", "T1"], tasks) != first
        assert stable_batch_id("run-1", ["T1", "T2"], [_task("T1", attempts=1), tasks[1]]) != first


class TestWorkerStateBoundary:
    def test_worker_state_is_deeply_isolated_from_parent(self):
        parent = empty_dev_state("p1", "run-1", "request")
        parent["task_dag"] = [_task("T1").model_dump(mode="json")]
        parent["changed_files"] = [{"path": "parent.py", "task_id": "parent"}]
        parent["scratch"] = {"parent": True}

        worker = make_worker_state(
            parent,
            task_id="T1",
            batch_id="batch-1",
            workspace_path="C:/tasks/T1",
            branch="agent/task-run-t1",
        )
        worker["task_dag"][0]["status"] = TaskStatus.RUNNING.value
        worker["changed_files"].append({"path": "worker.py", "task_id": "T1"})

        assert worker["active_task_id"] == "T1"
        assert worker["workspace_path"] == "C:/tasks/T1"
        assert worker["branch"] == "agent/task-run-t1"
        assert worker["scratch"] == {"batch_id": "batch-1"}
        assert worker["validation"] == {}
        assert parent["task_dag"][0]["status"] == TaskStatus.READY.value
        assert parent["changed_files"] == [{"path": "parent.py", "task_id": "parent"}]
        assert parent["scratch"] == {"parent": True}

    def test_worker_result_contains_only_task_scoped_data(self):
        worker = empty_dev_state("p1", "run-1", "request")
        worker.update(
            {
                "active_task_id": "T1",
                "task_dag": [_task("T1", attempts=2).model_dump(mode="json")],
                "changed_files": [{"path": "app/api.py", "task_id": "T1"}],
                "validation": {"passed": True},
                "scratch": {
                    "batch_id": "batch-1",
                    "coding_result": {"status": "done", "summary": "implemented", "notes": ""},
                },
            }
        )

        result = task_result_from_state(worker)

        assert result == {
            "batch_id": "batch-1",
            "task_id": "T1",
            "status": "done",
            "summary": "implemented",
            "error": "",
            "changed_files": [{"path": "app/api.py", "task_id": "T1"}],
            "validation": {"passed": True},
            "task": _task("T1", attempts=2).model_dump(mode="json"),
        }
