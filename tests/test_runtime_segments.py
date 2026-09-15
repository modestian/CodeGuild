"""执行段预算回归测试：会话复用（重试 / 继续迭代 / 审批恢复）不得立即命中停止条件。

背景：coder / tester / reviewer 跨任务重试与人工「继续迭代」复用同一 RuntimeSession。
旧行为下预算计数器（steps / tokens / cost / tool_failures / 墙钟）跨执行段累计：
上一段因 token 到顶（max_tokens）或轮次上限（max_steps）而 stopped 后，
续跑时会在循环入口被 _stop_reason 立即判停——用户表现为"继续迭代立即失败、无任何动作"。

修复后的语义：
1. 新执行段（上一段 finished / stopped / failed）重置预算计数器，保留对话记忆；
2. 审批恢复（awaiting_approval）属同一执行段：仅重置墙钟（人工等待不计入 Agent 时间）；
3. 已挂起的（已获批）工具调用优先于停止条件执行。
"""
from __future__ import annotations

import time
from pathlib import Path

from app.harness.permission import PROFILES
from app.harness.session import RuntimeSession
from app.schemas.events import EventType as ET
from app.storage import repositories as repo
from tests.test_graph_flows import (
    ARCHITECTURE,
    CODER_FINAL,
    EDIT_CORE_V1,
    EDIT_TEST,
    READ_CORE,
    REQUIREMENTS,
    RUN_TEST_CALL,
    _events,
    _run_row,
    _start_run,
    _tester_report,
    reviewer_script,
)

# =========================================================
# 单元级：AgentRuntime 执行段预算
# =========================================================


async def _make_run(app_ctx, repo_path: Path):
    async with app_ctx.database.session() as session:
        project = await repo.create_project(session, name="noteapp", repo_path=str(repo_path))
        run = await repo.create_run(session, project.id, "为 NoteStore 增加 delete 功能")
    return project.id, run.id


def _coder_session(run_id: str, *, status: str, **overrides) -> RuntimeSession:
    session = RuntimeSession(
        session_id=f"{run_id}:coder:T1",
        run_id=run_id,
        agent="coder",
        task_id="T1",
        status=status,
        messages=[
            {"role": "system", "content": "你是编码 Agent。"},
            {"role": "user", "content": "## Current Task\n实现 NoteStore.delete"},
        ],
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


async def _run_coder(app_ctx, run_id: str, project_id: str, repo_path: Path, session: RuntimeSession):
    ctx_factory = app_ctx.make_ctx_factory(
        run_id=run_id, project_id=project_id, agent="coder", workspace=repo_path
    )
    return await app_ctx.runtime.run(
        run_id=run_id,
        agent="coder",
        system_prompt="你是编码 Agent。",
        task_brief="",
        ctx_factory=ctx_factory,
        output_schema=None,
        mode="agentic",
        session=session,
        task_id="T1",
    )


async def _event_messages(app_ctx, run_id: str) -> list[str]:
    async with app_ctx.database.session() as session:
        rows = await repo.list_events(session, run_id)
    return [str(r.message) for r in rows]


class TestNewSegmentResetsBudget:
    async def test_resume_after_budget_stop_starts_fresh_budget(self, app_ctx, sample_repo):
        """上一段因 token 到顶 / 轮次上限 / 超时 stopped → 续跑重置预算，实际执行而不立即判停。"""
        project_id, run_id = await _make_run(app_ctx, sample_repo)
        session = _coder_session(
            run_id,
            status="stopped",
            steps=50,  # 已达 coder profile max_steps
            input_tokens=250_000,  # 已超 agent_max_tokens=200000
            output_tokens=1_000,
            cost_usd=9.9,  # 已超 agent_max_cost_usd=5
            tool_failures=99,  # 已超 agent_max_tool_failures
            started_ts=time.time() - 9_999,  # 已超 agent_timeout_seconds
        )
        app_ctx.set_llm_script("coder", [CODER_FINAL])

        result = await _run_coder(app_ctx, run_id, project_id, sample_repo, session)

        assert result.status == "finished", result.stopped_reason or result.error
        assert session.steps == 1  # 计数器已重置，仅统计本执行段
        assert session.tool_failures == 0
        assert session.input_tokens + session.output_tokens < 250_000
        assert session.started_ts > time.time() - 60

        # 预算重置对用户可见（事件留痕）
        messages = await _event_messages(app_ctx, run_id)
        assert any("开始新的执行段" in m for m in messages), messages[-5:]

    async def test_fresh_session_not_affected(self, app_ctx, sample_repo):
        """新会话（running）不触发重置，行为保持原样。"""
        project_id, run_id = await _make_run(app_ctx, sample_repo)
        session = _coder_session(run_id, status="running")
        app_ctx.set_llm_script("coder", [CODER_FINAL])

        result = await _run_coder(app_ctx, run_id, project_id, sample_repo, session)

        assert result.status == "finished"
        assert session.steps == 1


class TestApprovalResumeSemantics:
    async def test_approval_resume_refreshes_wall_clock(self, app_ctx, sample_repo):
        """审批等待是人工时间：恢复时不因超时停止条件立即判停。"""
        project_id, run_id = await _make_run(app_ctx, sample_repo)
        session = _coder_session(
            run_id, status="awaiting_approval", started_ts=time.time() - 9_999
        )
        app_ctx.set_llm_script("coder", [CODER_FINAL])

        result = await _run_coder(app_ctx, run_id, project_id, sample_repo, session)

        assert result.status == "finished", result.stopped_reason or result.error

    async def test_approval_resume_keeps_token_budget(self, app_ctx, sample_repo):
        """审批恢复属同一执行段：token 预算继续累计（已耗尽则判停，不借审批重置预算）。"""
        project_id, run_id = await _make_run(app_ctx, sample_repo)
        session = _coder_session(
            run_id, status="awaiting_approval", input_tokens=250_000, output_tokens=1_000
        )
        app_ctx.set_llm_script("coder", [CODER_FINAL])

        result = await _run_coder(app_ctx, run_id, project_id, sample_repo, session)

        assert result.status == "stopped"
        assert "max_tokens" in result.stopped_reason

    async def test_pending_calls_execute_before_stop_check(self, app_ctx, sample_repo):
        """已挂起的工具调用优先于停止条件：批准后必须先执行实际动作，再考虑判停。"""
        project_id, run_id = await _make_run(app_ctx, sample_repo)
        session = _coder_session(
            run_id,
            status="awaiting_approval",
            input_tokens=250_000,  # 预算已耗尽
            output_tokens=1_000,
            pending_calls=[
                {"id": "call_1", "name": "read_file", "arguments": {"path": "noteapp/core.py"}}
            ],
        )
        app_ctx.set_llm_script("coder", [CODER_FINAL])

        result = await _run_coder(app_ctx, run_id, project_id, sample_repo, session)

        # 旧行为：停止条件先触发，pending 原样残留 → "批准"后无任何动作
        assert session.pending_calls == []
        tool_messages = [m for m in session.messages if m.get("role") == "tool"]
        assert tool_messages and tool_messages[-1].get("name") == "read_file"
        # 排空后仍受预算约束（避免借审批无限执行）
        assert result.status == "stopped"
        assert "max_tokens" in result.stopped_reason


# =========================================================
# 图级：预算停止 → 修复重试 → 实际继续推进并完成任务
# =========================================================


def _budget_coder_script() -> list:
    """第 1 执行段：计划 + 探索（达到 max_steps 上限而停止）；
    第 2 执行段：修复重试，完成真实修改与验证。"""
    return [
        {
            "decision": "tool_call",
            "tool": "update_plan",
            "arguments": {
                "task_id": "T1",
                "approach": "在 core.py 添加 delete 方法并补测试",
                "steps": ["读取 core.py", "添加 delete", "补充测试", "运行测试"],
                "files_to_change": ["noteapp/core.py", "tests/test_core.py"],
                "test_strategy": "pytest",
            },
            "rationale": "先制定计划",
        },
        READ_CORE,
        READ_CORE,
        READ_CORE,
        # ---- 第 2 执行段（修复重试：预算应已重置）----
        EDIT_CORE_V1,
        EDIT_TEST,
        RUN_TEST_CALL,
        CODER_FINAL,
        # 余量（防止意外进入修复导致脚本耗尽）
        READ_CORE,
        RUN_TEST_CALL,
        CODER_FINAL,
    ]


class TestBudgetStopThenRepair:
    async def test_repair_after_budget_stop_continues_with_fresh_budget(self, app_ctx, sample_repo):
        """任务因轮次上限失败后，修复重试必须真正继续工作（旧行为：立即再次判停 → 转人工）。"""
        # 仅本测试实例生效：调小 coder 轮次预算以快速触发停止条件
        app_ctx.permissions.profiles = {
            **PROFILES,
            "coder": PROFILES["coder"].model_copy(update={"max_steps": 4}),
        }
        scripts = {
            "product": [REQUIREMENTS],
            "architect": [ARCHITECTURE],
            "coder": _budget_coder_script(),
            "tester": [RUN_TEST_CALL, _tester_report(True)],
            "reviewer": reviewer_script(approve_first=True),
        }
        manager, run_id = await _start_run(app_ctx, sample_repo, scripts)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "approval_required"
        assert not payload.get("needs_human"), "修复重试后应完成任务，而不是转人工介入"

        async with app_ctx.database.session() as session:
            tasks = await repo.list_tasks(session, run_id)
        assert len(tasks) == 1 and tasks[0].status == "COMPLETED"

        # 发生过预算停止与修复，且修复轮次携带新执行段预算重置
        types = await _events(app_ctx, run_id)
        assert ET.TASK_FAILED.value in types
        assert ET.REPAIRING.value in types
        messages = await _event_messages(app_ctx, run_id)
        assert any("开始新的执行段" in m for m in messages)


# =========================================================
# 图级：用户场景「预算耗尽失败 → 转人工 → 继续迭代」必须真正续跑
# =========================================================


def _exhausting_coder_script() -> list:
    """第 1 段：update_plan + 探索（4 步耗尽 coder max_steps=4，计划持久化到会话）；
    第 2/3 段：各 4 次 read_file → 连续失败触发 MAX_CODE_RETRY 转人工；
    第 4 段（「继续迭代」后）：真实修改与验证完成（编辑守卫依赖会话内已记录的 plan）。"""
    script: list = [
        {
            "decision": "tool_call",
            "tool": "update_plan",
            "arguments": {
                "task_id": "T1",
                "approach": "在 core.py 添加 delete 方法并补测试",
                "steps": ["读取 core.py", "添加 delete", "补充测试", "运行测试"],
                "files_to_change": ["noteapp/core.py", "tests/test_core.py"],
                "test_strategy": "pytest",
            },
            "rationale": "先制定计划（计划跨执行段持久化）",
        },
        READ_CORE,
        READ_CORE,
        READ_CORE,
        # ---- 第 2 段：仍只有探索（4 步耗尽）----
        READ_CORE,
        READ_CORE,
        READ_CORE,
        READ_CORE,
        # ---- 第 3 段：仍只有探索 → 触发 MAX_CODE_RETRY → 转人工 ----
        READ_CORE,
        READ_CORE,
        READ_CORE,
        READ_CORE,
        # ---- 第 4 段（「继续迭代」后）：真实修改与验证 ----
        EDIT_CORE_V1,
        EDIT_TEST,
        RUN_TEST_CALL,
        CODER_FINAL,
        # 余量（防止意外进入修复导致脚本耗尽）
        READ_CORE,
        RUN_TEST_CALL,
        CODER_FINAL,
    ]
    return script


class TestContinueAfterNeedsHuman:
    async def test_continue_iteration_actually_resumes_after_budget_exhaustion(self, app_ctx, sample_repo):
        """用户场景：任务因轮次上限失败并转人工 → 点击「继续迭代」必须真正继续执行。

        旧行为：会话预算计数器跨执行段累计 → 续跑在循环入口立即再次判停 → 再次转人工
        （用户表现：继续迭代后立即报错、无任何动作）。
        """
        # 仅本测试实例生效：调小 coder 轮次预算以快速触发连续停止
        app_ctx.permissions.profiles = {
            **PROFILES,
            "coder": PROFILES["coder"].model_copy(update={"max_steps": 4}),
        }
        scripts = {
            "product": [REQUIREMENTS],
            "architect": [ARCHITECTURE],
            "coder": _exhausting_coder_script(),
            "tester": [RUN_TEST_CALL, _tester_report(True)],
            "reviewer": reviewer_script(approve_first=True),
        }
        manager, run_id = await _start_run(app_ctx, sample_repo, scripts)

        # ---- 阶段 1：预算停止 → 自动修复重试 → 达到 MAX_CODE_RETRY → 转人工 ----
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "approval_required"
        assert payload.get("needs_human"), f"连续预算停止后应转人工介入: {payload}"
        assert "continue" in (payload.get("options") or []), payload
        assert "MAX_CODE_RETRY" in str(payload.get("reason") or ""), payload

        # ---- 阶段 2：用户点击「继续迭代」并补充要求（note → guidance） ----
        await manager.submit_approval(run_id, "continue", note="请先完成 delete 实现并运行测试再收尾")
        await manager.wait(run_id)

        # ---- 阶段 3：必须真正继续执行至任务完成（旧行为：续跑立即判停 → 再次转人工） ----
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "approval_required"
        assert not payload.get("needs_human"), f"继续迭代后不应再次要求人工介入: {payload}"

        async with app_ctx.database.session() as session:
            tasks = await repo.list_tasks(session, run_id)
        assert len(tasks) == 1 and tasks[0].status == "COMPLETED"

        core = (Path(run.workspace_path) / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "def delete" in core

        # ---- 会话复用留痕：≥3 次执行段重置（自动修复 ×2 + 继续迭代 ×1），含 stopped → 新段 ----
        async with app_ctx.database.session() as session:
            rows = await repo.list_events(session, run_id)
        resets = [r for r in rows if r.type == ET.LOG.value and "开始新的执行段" in str(r.message)]
        assert len(resets) >= 3, [str(r.message) for r in resets]
        assert any(
            str(((r.data or {}).get("previous_segment") or {}).get("status")) == "stopped"
            for r in resets
        ), [r.data for r in resets]

        # 用户补充要求已注入修复上下文
        assert any("额外需求已注入修复上下文" in str(r.message) for r in rows)
