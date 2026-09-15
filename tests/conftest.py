"""共享测试夹具：隔离配置 / AppContext / 示例 Git 仓库 / Mock 脚本。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.services.app_context import AppContext
from app.services.run_manager import RunManager
from app.storage import repositories as repo

# =========================================================
# 示例仓库（noteapp）
# =========================================================

CORE_PY = '''"""NoteStore：简单的笔记存储。"""


class NoteStore:
    def __init__(self):
        self._notes = []

    def add(self, text: str) -> int:
        self._notes.append(text)
        return len(self._notes)

    def all(self):
        return list(self._notes)
'''

TEST_PY = '''import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from noteapp.core import NoteStore


def test_add():
    s = NoteStore()
    assert s.add("a") == 1


def test_all():
    s = NoteStore()
    s.add("a")
    s.add("b")
    assert s.all() == ["a", "b"]
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def sample_repo(tmp_path_factory) -> Path:
    repo_path = tmp_path_factory.mktemp("noteapp-repo")
    (repo_path / "noteapp").mkdir()
    (repo_path / "tests").mkdir()
    (repo_path / "noteapp" / "__init__.py").write_text(
        'from .core import NoteStore\n\n__all__ = ["NoteStore"]\n', encoding="utf-8"
    )
    (repo_path / "noteapp" / "core.py").write_text(CORE_PY, encoding="utf-8")
    (repo_path / "tests" / "test_core.py").write_text(TEST_PY, encoding="utf-8")
    (repo_path / "README.md").write_text("# NoteApp\n\n示例笔记应用（测试夹具）。\n", encoding="utf-8")

    assert _git(repo_path, "init", "-b", "main").returncode == 0
    assert _git(repo_path, "add", "-A").returncode == 0
    result = _git(
        repo_path,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@local",
        "commit",
        "-m",
        "init",
    )
    assert result.returncode == 0, result.stderr
    return repo_path


# =========================================================
# 配置 / AppContext
# =========================================================


@pytest.fixture
def settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    db_path = (data_dir / "test.db").as_posix()
    s = Settings(
        _env_file=None,  # 测试隔离：不受开发者本地 .env 影响（否则 mock_scripts_file 等会覆盖测试注入的脚本）
        data_dir=data_dir,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        llm_provider="mock",
        mock_scripts_file="",
        sandbox_mode="local",
        test_command=f'"{sys.executable}" -m pytest -q',
        lint_command="",
        build_command="",
        agent_max_steps=40,
        agent_max_tool_failures=8,
        supervisor_mode="fixed",
    )
    s.ensure_dirs()
    return s


@pytest.fixture
async def app_ctx(settings):
    ctx = AppContext(settings)
    await ctx.init()
    try:
        yield ctx
    finally:
        await ctx.close()


@pytest.fixture
async def run_env(app_ctx, sample_repo):
    """创建项目 + 运行（含工作区），返回 (ctx, manager, run_id, repo_path)。"""
    async with app_ctx.database.session() as session:
        project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
        run = await repo.create_run(session, project.id, "为 NoteStore 增加 delete 功能")
    manager = RunManager(app_ctx)
    await manager.start_run(run.id)
    return app_ctx, manager, run.id, sample_repo
