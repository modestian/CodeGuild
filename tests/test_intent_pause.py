"""意图路由（query/develop）与人工打断（pause/resume）测试。

覆盖：
1. mode=query：只读问答直接回答并结束（不进入开发闭环，无任务 / 无提交）
2. mode=auto：LLM 意图分类为 query → 只读回答（意图事件留痕）
3. 人工打断：安全点挂起（payload.type=pause）→ resume 携带补充需求 → 继续开发闭环并完成
4. 非执行中运行不可打断（RunConflict）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.events import EventType as ET
from app.services.run_manager import RunConflict, RunManager
from app.storage import repositories as repo
from tests.test_graph_flows import (
    ARCHITECTURE,
    REQUIREMENTS,
    RUN_TEST_CALL,
    _events,
    _run_row,
    _tester_report,
    coder_script,
    reviewer_script,
)

# =========================================================
# Mock 脚本
# =========================================================

READ_CORE = {
    "decision": "tool_call",
    "tool": "read_file",
    "arguments": {"path": "noteapp/core.py"},
    "rationale": "阅读实现",
}

ANSWER = {
    "decision": "final",
    "output": {
        "markdown": "NoteApp 是一个示例笔记应用：noteapp/core.py 中的 NoteStore 提供 add/all 方法，tests/test_core.py 覆盖基础行为。",
        "key_points": ["核心模块：noteapp/core.py（NoteStore）", "测试：tests/test_core.py"],
        "files_referenced": ["noteapp/core.py", "tests/test_core.py"],
    },
    "rationale": "只读回答",
}

INTENT_QUERY = {"intent": "query", "reason": "介绍类请求，无需修改文件"}
INTENT_DEVELOP = {"intent": "develop", "reason": "需要修改文件"}


async def _create_run(app_ctx, sample_repo: Path, request: str, mode: str = "auto") -> str:
    async with app_ctx.database.session() as session:
        project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
        run = await repo.create_run(session, project.id, request, mode=mode)
    return run.id


# =========================================================
# 1/2. 意图路由：只读问答
# =========================================================


class TestQueryIntent:
    async def test_explicit_query_mode_answers_without_development(self, app_ctx, sample_repo):
        app_ctx.set_llm_script("analyst", [READ_CORE, ANSWER])
        run_id = await _create_run(app_ctx, sample_repo, "介绍一下noteapp这个项目，简单一点", mode="query")
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"

        types = await _events(app_ctx, run_id)
        assert ET.ANSWER_READY.value in types
        assert ET.TASKS_GENERATED.value not in types  # 不进入开发闭环
        assert ET.COMMIT_DONE.value not in types

        # 回答内容入 State + 工件
        snapshot = await manager._get_graph().aget_state(manager._config(run_id))
        answer = snapshot.values.get("answer") or {}
        assert "NoteApp" in answer.get("markdown", "")
        assert (app_ctx.settings.artifacts_dir / run_id / "answer.json").exists()

        # 事件携带完整回答与结束摘要（AI 解说面板据此渲染）
        async with app_ctx.database.session() as session:
            rows = await repo.list_events(session, run_id)
        ready = next(r for r in rows if r.type == ET.ANSWER_READY.value)
        assert "NoteApp" in (ready.data.get("answer") or {}).get("markdown", "")
        finished = next(r for r in rows if r.type == ET.RUN_FINISHED.value)
        assert "只读问答" in str(finished.data.get("summary") or "")

    async def test_auto_mode_classified_as_query(self, app_ctx, sample_repo):
        app_ctx.set_llm_script("intent_router", [INTENT_QUERY])
        app_ctx.set_llm_script("analyst", [ANSWER])
        run_id = await _create_run(app_ctx, sample_repo, "介绍一下noteapp这个项目，简单一点", mode="auto")
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"

        types = await _events(app_ctx, run_id)
        assert ET.INTENT_DECIDED.value in types
        snapshot = await manager._get_graph().aget_state(manager._config(run_id))
        assert snapshot.values.get("request_intent") == "query"

    async def test_auto_mode_classified_as_develop(self, app_ctx, sample_repo):
        app_ctx.set_llm_script("intent_router", [INTENT_DEVELOP])
        app_ctx.set_llm_script("product", [REQUIREMENTS])
        app_ctx.set_llm_script("architect", [ARCHITECTURE])
        app_ctx.set_llm_script("coder", coder_script(rounds=1))
        app_ctx.set_llm_script("tester", [RUN_TEST_CALL, _tester_report(True)])
        app_ctx.set_llm_script("reviewer", reviewer_script(approve_first=True))
        run_id = await _create_run(app_ctx, sample_repo, "为 NoteStore 增加 delete 功能", mode="auto")
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval"  # 进入开发闭环 → 到达人工交付审批
        snapshot = await manager._get_graph().aget_state(manager._config(run_id))
        assert snapshot.values.get("request_intent") == "develop"


# =========================================================
# 3/4. 人工打断（pause/resume）
# =========================================================


class TestPauseResume:
    async def test_pause_safe_point_then_resume_with_guidance(self, app_ctx, sample_repo):
        holder: dict = {}

        def product_with_pause(_messages):
            # Product 执行期间登记打断请求 → 下一个安全点（Supervisor 入口）挂起
            app_ctx.controls.request_pause(holder["run_id"])
            return REQUIREMENTS

        app_ctx.set_llm_script("product", [product_with_pause])
        app_ctx.set_llm_script("architect", [ARCHITECTURE])
        app_ctx.set_llm_script("coder", coder_script(rounds=1))
        app_ctx.set_llm_script("tester", [RUN_TEST_CALL, _tester_report(True)])
        app_ctx.set_llm_script("reviewer", reviewer_script(approve_first=True))

        run_id = await _create_run(app_ctx, sample_repo, "为 NoteStore 增加 delete 功能", mode="develop")
        holder["run_id"] = run_id
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        # 打断挂起
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "pause", f"payload={payload}"

        # 恢复并携带补充需求
        await manager.submit_approval(run_id, "resume", note="删除越界时抛 IndexError")
        await manager.wait(run_id)

        # 继续开发闭环 → 到达人工交付审批；载荷含超限诊断信息
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload.get("type") == "approval_required", f"payload={payload}"
        assert "retries" in payload and "max_code_retry" in payload

        # 补充需求已登记 + 恢复事件留痕
        items = await app_ctx.guidance.list(run_id)
        assert any("IndexError" in it["text"] for it in items)
        types = await _events(app_ctx, run_id)
        assert ET.PAUSE_RESUMED.value in types

        # 最终审批 → 提交完成
        await manager.submit_approval(run_id, "approve")
        await manager.wait(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"

    async def test_pause_then_reject_cancels_run(self, app_ctx, sample_repo):
        """暂停面板选择「取消运行」（reject）：不恢复图，直接收尾为 cancelled。"""
        holder: dict = {}

        def product_with_pause(_messages):
            app_ctx.controls.request_pause(holder["run_id"])
            return REQUIREMENTS

        app_ctx.set_llm_script("product", [product_with_pause])
        run_id = await _create_run(app_ctx, sample_repo, "为 NoteStore 增加 delete 功能", mode="develop")
        holder["run_id"] = run_id
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "pause", f"payload={payload}"
        assert payload.get("options") == ["resume", "reject"]
        assert payload.get("approval_id")  # 每次挂起唯一标识

        await manager.submit_approval(run_id, "reject", note="方向调整，取消本次运行")
        run = await _run_row(app_ctx, run_id)
        assert run.status == "cancelled", f"status={run.status} error={run.error}"

        types = await _events(app_ctx, run_id)
        assert ET.RUN_CANCELLED.value in types
        assert ET.PAUSE_RESUMED.value not in types  # 未恢复执行

    async def test_pause_rejected_when_not_running(self, app_ctx, sample_repo):
        app_ctx.set_llm_script("analyst", [ANSWER])
        run_id = await _create_run(app_ctx, sample_repo, "介绍一下noteapp这个项目", mode="query")
        manager = RunManager(app_ctx)
        await manager.start_run(run_id)
        await manager.wait(run_id)

        with pytest.raises(RunConflict):
            await manager.request_pause(run_id)
