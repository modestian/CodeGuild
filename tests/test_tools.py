"""工具执行链测试：Schema 校验 / 计划门禁 / 路径穿越防护 / 权限拒绝 / apply_patch。"""
from __future__ import annotations

from pathlib import Path

from app.harness.registry import ToolContext
from app.harness.session import RuntimeSession
from app.schemas.tool import PolicyAction, ToolCall


def _ctx(app_ctx, workspace: Path, agent: str = "coder", session: RuntimeSession | None = None) -> ToolContext:
    session = session or RuntimeSession(session_id="t-session", run_id="run-test", agent=agent)
    return ToolContext(
        run_id="run-test",
        project_id="p-test",
        agent=agent,
        workspace=workspace,
        session=session,
        settings=app_ctx.settings,
        sandbox=app_ctx.sandbox,
        artifacts_dir=None,
        emit=None,
    )


class TestPlanGate:
    async def test_edit_requires_plan_for_coder(self, app_ctx, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path)
        result = await app_ctx.executor.execute(
            ToolCall(name="edit_file", arguments={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"}),
            ctx,
        )
        assert not result.ok
        assert "update_plan" in (result.error or "")
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_edit_allowed_after_plan(self, app_ctx, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path)
        plan = await app_ctx.executor.execute(
            ToolCall(
                name="update_plan",
                arguments={"task_id": "T1", "approach": "改 x", "steps": ["编辑"], "files_to_change": ["a.py"]},
            ),
            ctx,
        )
        assert plan.ok
        result = await app_ctx.executor.execute(
            ToolCall(name="edit_file", arguments={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"}),
            ctx,
        )
        assert result.ok, result.error
        assert target.read_text(encoding="utf-8") == "x = 2\n"
        assert ctx.session.changed_files.get("a.py") == "edit"


class TestPaths:
    async def test_path_traversal_blocked(self, app_ctx, tmp_path):
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path)
        result = await app_ctx.executor.execute(
            ToolCall(name="read_file", arguments={"path": "../outside.txt"}), ctx
        )
        assert not result.ok
        assert "越界" in (result.error or "") or "策略拒绝" in (result.error or "")

    async def test_read_file_with_line_numbers(self, app_ctx, tmp_path):
        f = tmp_path / "b.py"
        f.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path)
        result = await app_ctx.executor.execute(
            ToolCall(name="read_file", arguments={"path": "b.py", "start_line": 2, "end_line": 4}), ctx
        )
        assert result.ok
        assert "line2" in result.data["content"]
        assert result.data["total_lines"] == 10


class TestPermissions:
    async def test_reviewer_edit_rejected_via_executor(self, app_ctx, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path, agent="reviewer")
        result = await app_ctx.executor.execute(
            ToolCall(name="edit_file", arguments={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"}),
            ctx,
        )
        assert not result.ok
        assert result.decision == PolicyAction.REJECT
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_schema_validation_error(self, app_ctx, tmp_path):
        ctx = _ctx(app_ctx, tmp_path)
        result = await app_ctx.executor.execute(ToolCall(name="edit_file", arguments={}), ctx)
        assert not result.ok
        assert "参数校验失败" in (result.error or "")

    async def test_unknown_tool(self, app_ctx, tmp_path):
        ctx = _ctx(app_ctx, tmp_path)
        result = await app_ctx.executor.execute(ToolCall(name="not_a_tool", arguments={}), ctx)
        assert not result.ok
        assert "未注册" in (result.error or "")


class TestFileOps:
    async def _plan_first(self, app_ctx, ctx) -> None:
        result = await app_ctx.executor.execute(
            ToolCall(name="update_plan", arguments={"approach": "test", "steps": ["edit"]}), ctx
        )
        assert result.ok

    async def test_create_file(self, app_ctx, tmp_path):
        ctx = _ctx(app_ctx, tmp_path)
        await self._plan_first(app_ctx, ctx)
        result = await app_ctx.executor.execute(
            ToolCall(name="create_file", arguments={"path": "pkg/new.py", "content": "y = 2\n"}), ctx
        )
        assert result.ok, result.error
        assert (tmp_path / "pkg" / "new.py").read_text(encoding="utf-8") == "y = 2\n"

    async def test_edit_ambiguous_old_string(self, app_ctx, tmp_path):
        f = tmp_path / "dup.py"
        f.write_text("a = 1\na = 1\n", encoding="utf-8")
        ctx = _ctx(app_ctx, tmp_path)
        await app_ctx.executor.execute(
            ToolCall(name="update_plan", arguments={"approach": "test", "steps": []}), ctx
        )
        result = await app_ctx.executor.execute(
            ToolCall(name="edit_file", arguments={"path": "dup.py", "old_string": "a = 1", "new_string": "a = 2"}),
            ctx,
        )
        assert not result.ok
        assert "不唯一" in (result.error or "")

    async def test_apply_patch(self, app_ctx, sample_repo):
        ctx = _ctx(app_ctx, sample_repo)
        await self._plan_first(app_ctx, ctx)
        # 按真实文件内容与行号构造 unified diff
        content = (sample_repo / "noteapp" / "core.py").read_text(encoding="utf-8")
        lines = content.splitlines()
        idx = lines.index("    def all(self):")  # 0-based
        start = idx  # 上一行（空行）的 1-based 行号
        patch = (
            "diff --git a/noteapp/core.py b/noteapp/core.py\n"
            "--- a/noteapp/core.py\n"
            "+++ b/noteapp/core.py\n"
            f"@@ -{start},3 +{start},6 @@\n"
            " \n"
            "     def all(self):\n"
            "         return list(self._notes)\n"
            "+\n"
            "+    def count(self) -> int:\n"
            "+        return len(self._notes)\n"
        )
        result = await app_ctx.executor.execute(ToolCall(name="apply_patch", arguments={"patch": patch}), ctx)
        assert result.ok, result.error
        assert "def count" in (sample_repo / "noteapp" / "core.py").read_text(encoding="utf-8")
