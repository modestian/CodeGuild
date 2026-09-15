"""交互式 HITL 测试：逐步确认（interactive）审批模式、追加需求、人工终止。

覆盖：
1. interactive：edit_file 逐步确认——approve_once 消费后同工具再次询问（每次询问语义）
2. interactive：approve_always 后续免问（本运行内同类操作不再中断）
3. interactive：拒绝工具审批——编辑未生效、留痕 rejected；人工 cancel → cancelled
4. auto → interactive 运行中切换审批模式
5. GuidanceManager：追加需求登记 / 领取消费 / 留痕查询
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
    _git_log,
    _run_row,
    _tester_report,
    coder_script,
    reviewer_script,
)


def _scripts() -> dict:
    """精简脚本：coder 一轮编辑（EDIT_CORE_V1 → EDIT_TEST）→ 测试 → 审查通过。"""
    return {
        "product": [REQUIREMENTS],
        "architect": [ARCHITECTURE],
        "coder": coder_script(rounds=1),
        "tester": [RUN_TEST_CALL, _tester_report(True)],
        "reviewer": reviewer_script(approve_first=True),
    }


async def _start(app_ctx, sample_repo: Path, approval_mode: str = "interactive"):
    for agent, script in _scripts().items():
        app_ctx.set_llm_script(agent, script)
    async with app_ctx.database.session() as session:
        project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
        run = await repo.create_run(
            session, project.id, "为 NoteStore 增加 delete 功能", approval_mode=approval_mode
        )
    manager = RunManager(app_ctx)
    await manager.start_run(run.id)
    await manager.wait(run.id)
    return manager, run.id


async def _approvals(app_ctx, run_id: str) -> list:
    async with app_ctx.database.session() as session:
        return list(await repo.list_approvals(session, run_id))


class TestInteractiveOnceMode:
    async def test_approve_once_asks_again_and_guidance_applied(self, app_ctx, sample_repo):
        manager, run_id = await _start(app_ctx, sample_repo)

        # 第一处编辑挂起：edit_file 逐步确认中断
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        assert run.approval_mode == "interactive"

        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "tool_approval"
        assert payload["tool"] == "edit_file"
        assert payload["approval_mode"] == "interactive"
        assert payload["options"] == ["approve_once", "approve_always", "reject"]

        # 运行中追加需求：恢复后应由执行循环领取并注入
        await app_ctx.guidance.add(run_id, "delete 越界时抛出的错误信息保持英文")

        # 批准本次 → 第二处 edit_file（写测试文件）再次询问（once 语义）
        await manager.submit_approval(run_id, "approve_once", note="仅同意本次")
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "tool_approval" and payload["tool"] == "edit_file"

        # 第一次编辑已生效（批准消费成功）
        core = (Path(run.workspace_path) / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "def delete" in core

        # 留痕：第一条 edit_file 审批为 approved + scope=once + 已消费
        records = await _approvals(app_ctx, run_id)
        edit_records = [r for r in records if r.tool == "edit_file"]
        assert len(edit_records) >= 2  # 第一条已消费 + 第二条重新询问
        assert edit_records[0].status == "approved"
        assert edit_records[0].scope == "once"
        assert edit_records[0].consumed is True

        # 再次批准本次 → 工具级审批全部通过，进入人工交付审批
        await manager.submit_approval(run_id, "approve_once")
        await manager.wait(run_id)
        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "approval_required"
        assert payload["options"] == ["approve", "reject"]

        # 人工交付批准 → 提交完成
        await manager.submit_approval(run_id, "approve", note="deliver")
        await manager.wait(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"

        log = _git_log(Path(run.workspace_path))
        assert "Multi-Agent Copilot run" in log

        # 事件：≥3 次审批中断（2 次工具 + 1 次交付）；补充要求已注入
        types = await _events(app_ctx, run_id)
        assert types.count(ET.APPROVAL_REQUIRED.value) >= 3
        assert types.count(ET.APPROVAL_RECEIVED.value) >= 3
        assert ET.GUIDANCE_APPLIED.value in types

        # 补充要求已消费（领取即消费）
        items = await app_ctx.guidance.list(run_id)
        assert items and items[0]["status"] == "consumed"


class TestInteractiveAlwaysMode:
    async def test_approve_always_skips_subsequent(self, app_ctx, sample_repo):
        manager, run_id = await _start(app_ctx, sample_repo)

        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "tool_approval" and payload["tool"] == "edit_file"

        # 批准后续免问
        await manager.submit_approval(run_id, "approve_always", note="本运行内 edit_file 免问")
        await manager.wait(run_id)

        # 第二处 edit_file 不再中断，直接到达人工交付审批
        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "approval_required", f"unexpected payload={payload}"
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval"

        # 两处编辑均已生效
        ws = Path(run.workspace_path)
        assert "def delete" in (ws / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "test_delete" in (ws / "tests" / "test_core.py").read_text(encoding="utf-8")

        # 留痕：仅一条 edit_file 记录，scope=always
        records = await _approvals(app_ctx, run_id)
        edit_records = [r for r in records if r.tool == "edit_file"]
        assert len(edit_records) == 1
        assert edit_records[0].status == "approved"
        assert edit_records[0].scope == "always"

        await manager.submit_approval(run_id, "approve")
        await manager.wait(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"


class TestInteractiveRejectAndCancel:
    async def test_reject_tool_then_cancel_run(self, app_ctx, sample_repo):
        manager, run_id = await _start(app_ctx, sample_repo)

        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "tool_approval" and payload["tool"] == "edit_file"

        # 拒绝本次编辑（once 语义：拒绝后同工具再问）
        await manager.submit_approval(run_id, "reject", note="不同意在当前实现上修改")
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "tool_approval" and payload["tool"] == "edit_file"

        # 被拒绝的编辑未生效
        core = (Path(run.workspace_path) / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "def delete" not in core

        # 留痕：存在 rejected 的 edit_file 审批
        records = await _approvals(app_ctx, run_id)
        rejected = [r for r in records if r.status == "rejected"]
        assert rejected and rejected[0].tool == "edit_file"

        # 人工终止（挂起态）：直接标记 cancelled
        await manager.cancel(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "cancelled"
        types = await _events(app_ctx, run_id)
        assert ET.RUN_CANCELLED.value in types

        # 已取消的运行不可再提交审批
        with pytest.raises(RunConflict):
            await manager.submit_approval(run_id, "approve")
        with pytest.raises(RunConflict):
            await manager.cancel(run_id)


class TestApprovalModeSwitch:
    async def test_auto_then_switch_interactive(self, app_ctx, sample_repo):
        # auto 模式：工具级编辑不中断，直达人工交付审批
        manager, run_id = await _start(app_ctx, sample_repo, approval_mode="auto")
        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"
        assert run.approval_mode == "auto"
        payload = manager.get_pending_payload(run_id)
        assert payload["type"] == "approval_required"

        # 运行中切换为逐步确认
        await manager.set_approval_mode(run_id, "interactive")
        run = await _run_row(app_ctx, run_id)
        assert run.approval_mode == "interactive"
        assert await app_ctx.approvals.mode_for(run_id) == "interactive"
        types = await _events(app_ctx, run_id)
        assert ET.LOG.value in types

        # 交付审批不受模式影响，仍可正常完成
        await manager.submit_approval(run_id, "approve")
        await manager.wait(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"


class TestGuidanceManager:
    async def test_add_drain_consume_and_list(self, app_ctx, sample_repo):
        async with app_ctx.database.session() as session:
            project = await repo.create_project(session, name="p", repo_path=str(sample_repo))
            run = await repo.create_run(session, project.id, "x")

        item = await app_ctx.guidance.add(run.id, "补充要求 A")
        assert item["text"] == "补充要求 A"

        drained = await app_ctx.guidance.drain(run.id)
        assert [d["id"] for d in drained] == [item["id"]]
        # 领取即消费：再次领取为空
        assert await app_ctx.guidance.drain(run.id) == []

        rows = await app_ctx.guidance.list(run.id)
        assert rows[0]["status"] == "consumed"
        assert rows[0]["consumed_at"]

    async def test_drain_empty_when_nothing_pending(self, app_ctx, sample_repo):
        async with app_ctx.database.session() as session:
            project = await repo.create_project(session, name="p2", repo_path=str(sample_repo))
            run = await repo.create_run(session, project.id, "y")
        assert await app_ctx.guidance.drain(run.id) == []
