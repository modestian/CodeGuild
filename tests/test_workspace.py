"""Workspace 绝对路径与 Mock 脚本文件加载的防回归测试。

背景（联调中发现的两个真实缺陷）：
1. data_dir 为相对路径时（默认 ./data），git worktree 相对仓库目录创建，
   而下游 Agent/沙箱相对服务进程 CWD 解析 workspace 路径 → 路径不存在
   （WinError 267 / 文件不存在）。
2. Mock provider 在服务（HTTP）模式下无法注入脚本，需要支持从 JSON 文件
   加载各 Agent 的脚本队列，并支持每次运行刷新。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.schemas.state import TaskRecord
from app.services.app_context import AppContext
from app.storage import repositories as repo
from app.tools.common import run_host_git
from app.workspace.manager import WorkspaceManager


class TestWorkspaceAbsolutePath:
    async def test_relative_data_dir_yields_absolute_workspace(self, tmp_path, sample_repo, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 模拟服务从任意 CWD 启动
        settings = Settings(
            _env_file=None,
            data_dir=Path("./data"),  # 相对路径（与默认配置相同场景）
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            sandbox_mode="local",
        )
        settings.ensure_dirs()
        manager = WorkspaceManager(settings)

        info = await manager.create_run_workspace(str(sample_repo), "noteapp", "0123456789abcdef")
        ws = Path(info.path)

        # 必须为绝对路径，且真实存在、内容完整
        assert ws.is_absolute(), f"workspace 必须是绝对路径: {ws}"
        assert ws.exists()
        assert (ws / "noteapp" / "core.py").is_file()

        # worktree 不应落在源仓库内部
        assert not ws.is_relative_to(sample_repo.resolve())

        await manager.cleanup(str(sample_repo), ws)


class TestFullDiffFallback:
    """full_diff 回退逻辑：提交后（工作区干净）仍能展示分支累计变更。

    需求背景：审批提交后 `git diff HEAD` 为空，前端无法回顾已提交的变更；
    full_diff 需回退到「分支相对基线」的 diff（基线 = 顶端第一个非 Agent 提交）。
    """

    async def test_diff_visible_after_commit(self, tmp_path, sample_repo):
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            sandbox_mode="local",
        )
        settings.ensure_dirs()
        manager = WorkspaceManager(settings)
        info = await manager.create_run_workspace(str(sample_repo), "noteapp", "0123456789abcdef")
        ws = Path(info.path)

        # 1) 未提交变更（审查窗口期）：diff 可见
        core = ws / "noteapp" / "core.py"
        core.write_text(core.read_text(encoding="utf-8") + "\n\ndef extra():\n    return 1\n", encoding="utf-8")
        diff_pending = await manager.full_diff(ws)
        assert "def extra" in diff_pending

        # 2) Agent 提交后（工作区干净）：回退展示分支相对基线的变更
        await manager.commit(ws, "Multi-Agent Copilot run 01234567: 测试提交")
        diff_committed = await manager.full_diff(ws)
        assert "def extra" in diff_committed

        # 3) 全新工作区（无任何变更）：diff 为空
        info2 = await manager.create_run_workspace(str(sample_repo), "noteapp", "fedcba9876543210")
        diff_clean = await manager.full_diff(Path(info2.path))
        assert diff_clean.strip() == ""

        await manager.cleanup(str(sample_repo), ws)
        await manager.cleanup(str(sample_repo), Path(info2.path))


class TestEnsureRepoReady:
    """导入非 Git 项目：ensure_repo_ready 自动初始化并创建基线提交。

    背景：用户导入普通项目文件夹（非 Git / 尚无提交）时注册被 400 拒绝，
    系统只能处理已有 Git 仓库。约束：基线提交作者必须非 "Multi-Agent Copilot"，
    否则 full_diff 的基线回溯（_branch_base）会跳过它，导致提交后无法展示 diff。
    """

    @staticmethod
    def _settings(tmp_path) -> Settings:
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            sandbox_mode="local",
        )
        settings.ensure_dirs()
        return settings

    async def test_non_git_folder_becomes_runnable(self, tmp_path):
        folder = tmp_path / "plain-project"
        folder.mkdir()
        (folder / "main.py").write_text("print('hi')\n", encoding="utf-8")
        manager = WorkspaceManager(self._settings(tmp_path))

        ok, note = await manager.ensure_repo_ready(str(folder))
        assert ok, note
        assert "已初始化" in note and "基线提交" in note

        # 初始化后即可创建运行工作区（worktree 前提成立）
        info = await manager.create_run_workspace(str(folder), "plain", "abc1234567890abc")
        ws = Path(info.path)
        assert (ws / "main.py").is_file()

        # 回归防护：文件夹必须成为独立仓库根，绝不能复用外层嵌套仓库
        code, out, _ = await run_host_git(folder, ["rev-parse", "--show-toplevel"])
        assert code == 0 and Path(out.strip()) == folder.resolve()

        # 基线提交作者不能是 Agent 标识（否则 diff 基线丢失）
        code, out, _ = await run_host_git(folder, ["log", "-1", "--format=%an"])
        assert code == 0 and out.strip() and out.strip() != "Multi-Agent Copilot"

        await manager.cleanup(str(folder), ws)

    async def test_nested_folder_gets_own_repo(self, tmp_path):
        """回归：文件夹位于另一个仓库内部时，必须初始化独立的新仓库。

        历史缺陷：is_git_repo 曾用 `rev-parse --is-inside-work-tree` 判断，
        对嵌套子目录也返回 true，导致 git add/commit 落到外层仓库
        （曾误提交整个外层项目仓库）。
        """
        outer = tmp_path / "outer-repo"
        outer.mkdir()
        code, _, err = await run_host_git(outer, ["init", "-b", "main"])
        assert code == 0, err

        nested = outer / "plain-project"
        nested.mkdir()
        (nested / "main.py").write_text("print('hi')\n", encoding="utf-8")

        manager = WorkspaceManager(self._settings(tmp_path))
        ok, note = await manager.ensure_repo_ready(str(nested))
        assert ok, note
        assert "已初始化" in note and "基线提交" in note

        # nested 成为独立仓库根；外层仓库保持无提交
        code, out, _ = await run_host_git(nested, ["rev-parse", "--show-toplevel"])
        assert code == 0 and Path(out.strip()) == nested.resolve()
        code, out, _ = await run_host_git(outer, ["rev-list", "--count", "--all"])
        assert code == 0 and out.strip() == "0"

    async def test_empty_folder_gets_empty_baseline(self, tmp_path):
        empty = tmp_path / "empty-dir"
        empty.mkdir()
        manager = WorkspaceManager(self._settings(tmp_path))

        ok, note = await manager.ensure_repo_ready(str(empty))
        assert ok, note
        code, _, _ = await run_host_git(empty, ["rev-parse", "--verify", "HEAD"])
        assert code == 0  # --allow-empty 建立了基线，worktree 才能创建

    async def test_existing_repo_is_untouched(self, tmp_path, sample_repo):
        manager = WorkspaceManager(self._settings(tmp_path))
        _, before, _ = await run_host_git(sample_repo, ["rev-parse", "HEAD"])

        ok, note = await manager.ensure_repo_ready(str(sample_repo))
        assert ok and note == "仓库已就绪"

        _, after, _ = await run_host_git(sample_repo, ["rev-parse", "HEAD"])
        assert before == after  # 不新增提交

    async def test_missing_path_rejected(self, tmp_path):
        manager = WorkspaceManager(self._settings(tmp_path))
        ok, note = await manager.ensure_repo_ready(str(tmp_path / "nope"))
        assert not ok and "不存在" in note


class TestMockScriptsFile:
    async def test_mock_scripts_loaded_and_reloaded(self, tmp_path):
        script_file = tmp_path / "scripts.json"
        script_file.write_text(
            json.dumps({"product": [{"summary": "x"}], "coder": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            mock_scripts_file=str(script_file),
        )
        ctx = AppContext(settings)
        await ctx.init()
        try:
            assert ctx._llm_scripts.get("product") == [{"summary": "x"}]
            # 每次运行刷新：内容一致但为独立副本（避免跨运行消耗残留）
            first = ctx._llm_scripts["product"]
            ctx.reload_mock_scripts()
            assert ctx._llm_scripts["product"] == first
            assert ctx._llm_scripts["product"] is not first
        finally:
            await ctx.close()

    async def test_missing_file_is_ignored(self, tmp_path):
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            mock_scripts_file=str(tmp_path / "not-exists.json"),
        )
        ctx = AppContext(settings)
        await ctx.init()
        try:
            assert ctx._llm_scripts == {}
        finally:
            await ctx.close()


class TestTaskPersistence:
    async def test_target_files_round_trip_through_task_repository(self, app_ctx):
        async with app_ctx.database.session() as session:
            project = await repo.create_project(session, name="p", repo_path="C:/repo")
            run = await repo.create_run(session, project.id, "request")
            await repo.sync_tasks(
                session,
                run.id,
                [TaskRecord(id="T1", title="API", target_files=["app/api.py"])],
            )

        async with app_ctx.database.session() as session:
            rows = await repo.list_tasks(session, run.id)

        assert list(rows[0].target_files) == ["app/api.py"]


class TestTaskWorkspaces:
    @staticmethod
    def _manager(tmp_path) -> WorkspaceManager:
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'db.sqlite').as_posix()}",
            llm_provider="mock",
            sandbox_mode="local",
        )
        settings.ensure_dirs()
        return WorkspaceManager(settings)

    async def test_task_worktrees_are_isolated_and_replayed_by_identity(self, tmp_path, sample_repo):
        manager = self._manager(tmp_path)
        run = await manager.create_run_workspace(str(sample_repo), "noteapp", "run123456789")
        run_path = Path(run.path)

        first = await manager.create_task_workspace(
            run_path, run.branch, "run123456789", "batch-a", "T1"
        )
        second = await manager.create_task_workspace(
            run_path, run.branch, "run123456789", "batch-a", "T2"
        )
        replay = await manager.create_task_workspace(
            run_path, run.branch, "run123456789", "batch-a", "T1"
        )

        assert Path(first.path).is_absolute()
        assert Path(first.path) != Path(second.path)
        assert first.branch != second.branch
        assert replay.path == first.path and replay.branch == first.branch

        first_file = Path(first.path) / "only-first.txt"
        first_file.write_text("first\n", encoding="utf-8")
        assert not (Path(second.path) / "only-first.txt").exists()
        assert not (run_path / "only-first.txt").exists()

        await manager.cleanup_task_workspace(run_path, Path(first.path))
        await manager.cleanup_task_workspace(run_path, Path(second.path))
        await manager.cleanup(str(sample_repo), run_path)

    async def test_distinct_task_ids_with_same_slug_get_distinct_worktrees(
        self, tmp_path, sample_repo
    ):
        manager = self._manager(tmp_path)
        run = await manager.create_run_workspace(str(sample_repo), "noteapp", "run133456789")
        run_path = Path(run.path)

        first = await manager.create_task_workspace(
            run_path, run.branch, "run133456789", "batch-a", "API/Auth"
        )
        second = await manager.create_task_workspace(
            run_path, run.branch, "run133456789", "batch-a", "API Auth"
        )

        try:
            assert first.path != second.path
            assert first.branch != second.branch
        finally:
            await manager.cleanup_task_workspace(run_path, Path(first.path))
            await manager.cleanup_task_workspace(run_path, Path(second.path))
            await manager.cleanup(str(sample_repo), run_path)

    async def test_task_commit_integrates_once(self, tmp_path, sample_repo):
        manager = self._manager(tmp_path)
        run = await manager.create_run_workspace(str(sample_repo), "noteapp", "run223456789")
        run_path = Path(run.path)
        task = await manager.create_task_workspace(
            run_path, run.branch, "run223456789", "batch-a", "T1"
        )
        task_path = Path(task.path)
        (task_path / "task-one.txt").write_text("done\n", encoding="utf-8")

        commit = await manager.commit_task_workspace(task_path, "T1", "add task one")
        first = await manager.integrate_task_commit(run_path, commit["sha"], "T1")
        replay = await manager.integrate_task_commit(run_path, commit["sha"], "T1")

        assert first["integrated"] is True and first["already_integrated"] is False
        assert replay["integrated"] is True and replay["already_integrated"] is True
        assert (run_path / "task-one.txt").read_text(encoding="utf-8") == "done\n"

        await manager.cleanup_task_workspace(run_path, task_path)
        await manager.cleanup(str(sample_repo), run_path)

    async def test_conflicting_task_commit_aborts_without_overwriting_run(self, tmp_path, sample_repo):
        manager = self._manager(tmp_path)
        run = await manager.create_run_workspace(str(sample_repo), "noteapp", "run323456789")
        run_path = Path(run.path)
        first = await manager.create_task_workspace(
            run_path, run.branch, "run323456789", "batch-a", "T1"
        )
        second = await manager.create_task_workspace(
            run_path, run.branch, "run323456789", "batch-a", "T2"
        )
        first_core = Path(first.path) / "noteapp" / "core.py"
        second_core = Path(second.path) / "noteapp" / "core.py"
        first_core.write_text(first_core.read_text(encoding="utf-8").replace("return list(self._notes)", "return tuple(self._notes)"), encoding="utf-8")
        second_core.write_text(second_core.read_text(encoding="utf-8").replace("return list(self._notes)", "return self._notes.copy()"), encoding="utf-8")

        first_commit = await manager.commit_task_workspace(Path(first.path), "T1", "tuple result")
        second_commit = await manager.commit_task_workspace(Path(second.path), "T2", "copy result")
        assert (await manager.integrate_task_commit(run_path, first_commit["sha"], "T1"))["integrated"] is True

        conflict = await manager.integrate_task_commit(run_path, second_commit["sha"], "T2")

        assert conflict["integrated"] is False
        assert conflict["conflict"] is True
        assert conflict["conflict_files"] == ["noteapp/core.py"]
        assert "return tuple(self._notes)" in (run_path / "noteapp" / "core.py").read_text(encoding="utf-8")
        code, out, _ = await run_host_git(run_path, ["status", "--porcelain"])
        assert code == 0 and out.strip() == ""

        await manager.cleanup_task_workspace(run_path, Path(first.path))
        await manager.cleanup_task_workspace(run_path, Path(second.path))
        await manager.cleanup(str(sample_repo), run_path)
