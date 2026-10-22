"""并行 Coding 调度、Worker 隔离与 Development Graph 测试。"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from app.graph.development_graph import build_development_graph
from app.graph.parallel_coding import (
    make_worker_state,
    select_parallel_batch,
    stable_batch_id,
    task_result_from_state,
)
from app.schemas.state import TaskRecord, TaskStatus, empty_dev_state
from app.storage import repositories as repo
from app.tools.common import run_host_git


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


class _BarrierCodingGraph:
    def __init__(self, parties: int = 2):
        self.parties = parties
        self.started: set[str] = set()
        self.workspaces: dict[str, str] = {}
        self.active = 0
        self.max_active = 0
        self.all_started = asyncio.Event()

    async def ainvoke(self, state: dict) -> dict:
        task_id = str(state["active_task_id"])
        self.started.add(task_id)
        self.workspaces[task_id] = str(state["workspace_path"])
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if len(self.started) >= self.parties:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=3)
        await asyncio.sleep(0.02)
        result = copy.deepcopy(state)
        result["scratch"]["coding_result"] = {
            "status": "blocked",
            "summary": "",
            "notes": "intentional test stop",
        }
        result["validation"] = {"passed": False, "reason": "intentional test stop"}
        for task in result["task_dag"]:
            if task.get("id") == task_id:
                task["status"] = TaskStatus.RUNNING.value
                task["attempts"] = 99
        self.active -= 1
        return result


class _ControlledCodingGraph:
    def __init__(self, outcomes: dict[str, str], parties: int):
        self.outcomes = outcomes
        self.parties = parties
        self.started: list[str] = []
        self.workspaces: dict[str, str] = {}
        self.active = 0
        self.max_active = 0
        self.ready = asyncio.Event()

    async def ainvoke(self, state: dict) -> dict:
        task_id = str(state["active_task_id"])
        self.started.append(task_id)
        self.workspaces[task_id] = str(state["workspace_path"])
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active >= self.parties:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=3)
        result = copy.deepcopy(state)
        task = next(item for item in result["task_dag"] if item.get("id") == task_id)
        task["status"] = TaskStatus.RUNNING.value
        if self.outcomes[task_id] == "done":
            task["attempts"] = int(task.get("attempts") or 0) + 1
            output = Path(result["workspace_path"]) / f"{task_id.lower()}.txt"
            output.write_text(f"{task_id} done\n", encoding="utf-8")
            result["changed_files"] = [
                {"path": output.name, "action": "create", "task_id": task_id}
            ]
            result["scratch"]["coding_result"] = {
                "status": "done",
                "summary": f"{task_id} implemented",
                "notes": "",
            }
            result["validation"] = {"passed": True}
            result["scratch"]["validation"] = {"passed": True}
        else:
            task["attempts"] = 99
            result["scratch"]["coding_result"] = {
                "status": "blocked",
                "summary": "",
                "notes": f"{task_id} failed",
            }
            result["validation"] = {"passed": False, "reason": f"{task_id} failed"}
            result["scratch"]["validation"] = {
                "passed": False,
                "reason": f"{task_id} failed",
            }
        await asyncio.sleep(0.02)
        self.active -= 1
        if self.active == 0:
            self.ready.clear()
        return result


class _RaisingCodingGraph:
    def __init__(self):
        self.calls = 0
        self.workspaces: set[str] = set()

    async def ainvoke(self, state: dict) -> dict:
        self.calls += 1
        self.workspaces.add(str(state["workspace_path"]))
        raise RuntimeError("intentional worker crash")


class TestParallelDevelopmentGraph:
    @staticmethod
    async def _state(app_ctx, sample_repo, tasks: list[TaskRecord], approval_mode: str = "auto"):
        async with app_ctx.database.session() as session:
            project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
            run = await repo.create_run(
                session, project.id, "parallel", approval_mode=approval_mode
            )
        run_ws = await app_ctx.workspaces.create_run_workspace(
            str(sample_repo), "noteapp", run.id
        )
        async with app_ctx.database.session() as session:
            await repo.sync_tasks(session, run.id, tasks)
        state = empty_dev_state(project.id, run.id, "parallel")
        state.update(
            {
                "workspace_path": run_ws.path,
                "branch": run_ws.branch,
                "task_dag": [task.model_dump(mode="json") for task in tasks],
                "ready_tasks": [task.id for task in tasks if task.status == TaskStatus.READY],
                "run_status": "running",
            }
        )
        return state, run_ws

    async def test_two_ready_tasks_overlap_in_distinct_worktrees(self, app_ctx, sample_repo):
        async with app_ctx.database.session() as session:
            project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
            run = await repo.create_run(session, project.id, "parallel", approval_mode="auto")
        run_ws = await app_ctx.workspaces.create_run_workspace(
            str(sample_repo), "noteapp", run.id
        )
        tasks = [_task("T1"), _task("T2")]
        async with app_ctx.database.session() as session:
            await repo.sync_tasks(session, run.id, tasks)
        state = empty_dev_state(project.id, run.id, "parallel")
        state.update(
            {
                "workspace_path": run_ws.path,
                "branch": run_ws.branch,
                "task_dag": [task.model_dump(mode="json") for task in tasks],
                "ready_tasks": ["T1", "T2"],
                "run_status": "running",
            }
        )
        fake = _BarrierCodingGraph()

        try:
            graph = build_development_graph(app_ctx, coding_graph=fake)
            await graph.ainvoke(state)

            assert fake.started == {"T1", "T2"}
            assert fake.max_active == 2
            assert len(set(fake.workspaces.values())) == 2
            assert all(Path(path).exists() for path in fake.workspaces.values())
        finally:
            for path in fake.workspaces.values():
                await app_ctx.workspaces.cleanup_task_workspace(Path(run_ws.path), Path(path))
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_integration_keeps_success_blocks_dependents_and_replays_once(
        self, app_ctx, sample_repo
    ):
        tasks = [
            _task("T1"),
            _task("T2"),
            TaskRecord(
                id="T3",
                title="T3",
                dependencies=["T2"],
                status=TaskStatus.PENDING,
            ),
        ]
        state, run_ws = await self._state(app_ctx, sample_repo, tasks)
        fake = _ControlledCodingGraph({"T1": "done", "T2": "failed"}, parties=2)
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            result = await graph.ainvoke(copy.deepcopy(state))
            statuses = {task["id"]: task["status"] for task in result["task_dag"]}

            assert fake.max_active == 2
            assert statuses == {
                "T1": TaskStatus.COMPLETED.value,
                "T2": TaskStatus.FAILED.value,
                "T3": TaskStatus.BLOCKED.value,
            }
            assert (Path(run_ws.path) / "t1.txt").read_text(encoding="utf-8") == "T1 done\n"
            assert not (Path(run_ws.path) / "t2.txt").exists()

            await graph.ainvoke(copy.deepcopy(state))
            code, commits, _ = await run_host_git(
                Path(run_ws.path), ["log", "--format=%H", "--grep", "feat(T1)"]
            )
            assert code == 0
            assert len([line for line in commits.splitlines() if line.strip()]) == 1
        finally:
            for path in fake.workspaces.values():
                if Path(path).exists():
                    await app_ctx.workspaces.cleanup_task_workspace(
                        Path(run_ws.path), Path(path)
                    )
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_terminal_failure_does_not_skip_later_independent_tasks(
        self, app_ctx, sample_repo
    ):
        tasks = [_task("T1"), _task("T2"), _task("T3")]
        state, run_ws = await self._state(app_ctx, sample_repo, tasks)
        fake = _ControlledCodingGraph(
            {"T1": "failed", "T2": "done", "T3": "done"}, parties=1
        )
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            result = await graph.ainvoke(state)
            statuses = {task["id"]: task["status"] for task in result["task_dag"]}

            assert fake.started == ["T1", "T2", "T3"]
            assert statuses == {
                "T1": TaskStatus.FAILED.value,
                "T2": TaskStatus.COMPLETED.value,
                "T3": TaskStatus.COMPLETED.value,
            }
            assert result["needs_human"] is True
            assert "MAX_CODE_RETRY" in result["fail_reason"]
        finally:
            for path in fake.workspaces.values():
                if Path(path).exists():
                    await app_ctx.workspaces.cleanup_task_workspace(
                        Path(run_ws.path), Path(path)
                    )
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_interactive_mode_runs_ready_tasks_serially(self, app_ctx, sample_repo):
        tasks = [_task("T1"), _task("T2")]
        state, run_ws = await self._state(app_ctx, sample_repo, tasks, approval_mode="interactive")
        fake = _ControlledCodingGraph({"T1": "done", "T2": "failed"}, parties=1)
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            await graph.ainvoke(state)

            assert fake.started == ["T1", "T2"]
            assert fake.max_active == 1
            assert set(fake.workspaces.values()) == {run_ws.path}
        finally:
            for path in fake.workspaces.values():
                if Path(path).exists() and Path(path) != Path(run_ws.path):
                    await app_ctx.workspaces.cleanup_task_workspace(
                        Path(run_ws.path), Path(path)
                    )
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_disabled_parallel_setting_uses_serial_compatibility_path(
        self, app_ctx, sample_repo
    ):
        tasks = [_task("T1"), _task("T2")]
        state, run_ws = await self._state(app_ctx, sample_repo, tasks, approval_mode="auto")
        fake = _ControlledCodingGraph({"T1": "done", "T2": "failed"}, parties=1)
        previous = app_ctx.settings.parallel_coding_enabled
        app_ctx.settings.parallel_coding_enabled = False
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            await graph.ainvoke(state)

            assert fake.started == ["T1", "T2"]
            assert fake.max_active == 1
            assert set(fake.workspaces.values()) == {run_ws.path}
        finally:
            app_ctx.settings.parallel_coding_enabled = previous
            for path in fake.workspaces.values():
                if Path(path).exists() and Path(path) != Path(run_ws.path):
                    await app_ctx.workspaces.cleanup_task_workspace(
                        Path(run_ws.path), Path(path)
                    )
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_worker_exceptions_consume_retry_budget(self, app_ctx, sample_repo):
        state, run_ws = await self._state(app_ctx, sample_repo, [_task("T1")])
        fake = _RaisingCodingGraph()
        previous = app_ctx.settings.max_code_retry
        app_ctx.settings.max_code_retry = 2
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            result = await graph.ainvoke(state, {"recursion_limit": 20})

            task = next(item for item in result["task_dag"] if item["id"] == "T1")
            assert fake.calls == 2
            assert task["attempts"] == 2
            assert task["status"] == TaskStatus.FAILED.value
            assert result["needs_human"] is True
            assert "MAX_CODE_RETRY=2" in result["fail_reason"]
        finally:
            app_ctx.settings.max_code_retry = previous
            for path in fake.workspaces:
                if Path(path).exists():
                    await app_ctx.workspaces.cleanup_task_workspace(
                        Path(run_ws.path), Path(path)
                    )
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))

    async def test_cyclic_task_dag_stops_for_human_without_dispatching_workers(
        self, app_ctx, sample_repo
    ):
        tasks = [
            TaskRecord(
                id="T1",
                title="T1",
                dependencies=["T2"],
                status=TaskStatus.PENDING,
            ),
            TaskRecord(
                id="T2",
                title="T2",
                dependencies=["T1"],
                status=TaskStatus.PENDING,
            ),
        ]
        state, run_ws = await self._state(app_ctx, sample_repo, tasks)
        fake = _RaisingCodingGraph()
        graph = build_development_graph(app_ctx, coding_graph=fake)

        try:
            result = await graph.ainvoke(state)

            assert fake.calls == 0
            assert result["needs_human"] is True
            assert result["scratch"]["dev_stage"] == "blocked"
            assert "Task DAG" in result["fail_reason"]
            assert "循环依赖" in result["fail_reason"]
        finally:
            await app_ctx.workspaces.cleanup(str(sample_repo), Path(run_ws.path))
