"""端到端图流程测试（Mock LLM + 本地沙箱）：

1. 完整成功路径：Product → Architect → Coding → Testing → Review → 人工审批 → Commit
2. 人工拒绝路径：rejected，无提交
3. 自纠错闭环：Review 拒绝 → Repair → 复审通过 → 审批 → Commit

覆盖需求：FR-LG-01~06、FR-FIX-01~04、FR-HITL-01~05、FR-GIT-01~03、FR-OBS-01~03。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.schemas.events import EventType as ET
from app.services.run_manager import RunManager
from app.storage import repositories as repo
from tests.conftest import CORE_PY, TEST_PY

# =========================================================
# Mock LLM 脚本
# =========================================================

REQUIREMENTS = {
    "summary": "为 NoteStore 增加按索引删除笔记的能力",
    "features": [
        {"id": "F1", "name": "删除笔记", "description": "支持按索引删除笔记", "priority": "high"},
    ],
    "user_stories": [
        {"id": "US1", "as_a": "用户", "i_want": "删除指定笔记", "so_that": "管理笔记列表", "feature_id": "F1"},
    ],
    "acceptance_criteria": [
        {"id": "AC1", "description": "NoteStore.delete(index) 删除对应笔记；越界时抛出 IndexError", "feature_id": "F1"},
    ],
    "non_functional_requirements": [
        {"id": "NFR1", "category": "reliability", "description": "保持现有公共接口兼容"},
    ],
    "open_questions": [],
}

ARCHITECTURE = {
    "summary": "扩展 NoteStore：新增 delete(index) 方法",
    "design_overview": "在 noteapp/core.py 的 NoteStore 中新增 delete(index) 方法，并补充测试。",
    "modules": [
        {
            "name": "noteapp.core",
            "purpose": "笔记存储",
            "interfaces": ["NoteStore.delete(index)"],
            "files": ["noteapp/core.py"],
        }
    ],
    "api_contracts": [],
    "data_models": [],
    "module_dependencies": [],
    "constraints": ["保持 add/all 行为不变"],
    "tasks": [
        {
            "id": "T1",
            "title": "实现 NoteStore.delete 并补充测试",
            "description": "在 noteapp/core.py 增加 delete(index)；在 tests/test_core.py 增加 delete 测试。",
            "depends_on": [],
            "priority": "high",
            "acceptance_criteria": ["delete 删除对应元素", "越界抛 IndexError"],
        }
    ],
}

OLD_DELETE_ANCHOR = "    def all(self):\n        return list(self._notes)"

EDIT_CORE_V1 = {
    "decision": "tool_call",
    "tool": "edit_file",
    "arguments": {
        "path": "noteapp/core.py",
        "old_string": OLD_DELETE_ANCHOR,
        "new_string": OLD_DELETE_ANCHOR + "\n\n    def delete(self, index: int) -> None:\n        del self._notes[index]",
    },
    "rationale": "新增 delete 方法",
}

EDIT_CORE_V2 = {
    "decision": "tool_call",
    "tool": "edit_file",
    "arguments": {
        "path": "noteapp/core.py",
        "old_string": "    def delete(self, index: int) -> None:\n        del self._notes[index]",
        "new_string": (
            "    def delete(self, index: int) -> None:\n"
            "        if index < 0 or index >= len(self._notes):\n"
            '            raise IndexError("index out of range")\n'
            "        del self._notes[index]"
        ),
    },
    "rationale": "补充越界检查（Review 反馈）",
}

EDIT_TEST = {
    "decision": "tool_call",
    "tool": "edit_file",
    "arguments": {
        "path": "tests/test_core.py",
        "old_string": 'def test_add():\n    s = NoteStore()\n    assert s.add("a") == 1',
        "new_string": (
            'def test_add():\n    s = NoteStore()\n    assert s.add("a") == 1\n\n\n'
            "def test_delete():\n"
            "    s = NoteStore()\n"
            '    s.add("a")\n'
            '    s.add("b")\n'
            "    s.delete(0)\n"
            '    assert s.all() == ["b"]\n'
        ),
    },
    "rationale": "补充 delete 测试",
}

RUN_TEST_CALL = {"decision": "tool_call", "tool": "run_test", "arguments": {}, "rationale": "运行测试"}

READ_CORE = {
    "decision": "tool_call",
    "tool": "read_file",
    "arguments": {"path": "noteapp/core.py"},
    "rationale": "阅读现有实现",
}

CODER_FINAL = {
    "decision": "final",
    "output": {
        "status": "done",
        "summary": "实现 NoteStore.delete 并补充测试",
        "changed_files": ["noteapp/core.py", "tests/test_core.py"],
        "validation": "pytest 通过",
        "notes": "",
    },
    "rationale": "完成",
}


def coder_script(rounds: int = 1) -> list:
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
            "rationale": "先制定计划",
        },
        READ_CORE,
        EDIT_CORE_V1,
        EDIT_TEST,
        RUN_TEST_CALL,
        CODER_FINAL,
    ]
    # 额外的修复轮次（Review 拒绝后）
    if rounds >= 2:
        script += [READ_CORE, EDIT_CORE_V2, RUN_TEST_CALL, CODER_FINAL]
    # 冗余余量（防止意外进入修复）
    script += [READ_CORE, RUN_TEST_CALL, CODER_FINAL]
    return script


def _tester_report(passed: bool = True, total: int = 3, fail: int = 0) -> dict:
    return {
        "decision": "final",
        "output": {
            "passed": passed,
            "summary": {"total": total, "passed": total - fail, "failed": fail, "errors": 0, "skipped": 0},
            "failures": [] if passed else [{"test": "tests/test_core.py::test_delete", "message": "assert failed"}],
            "commands": ["python -m pytest -q"],
            "notes": "",
        },
        "rationale": "测试结果",
    }


def reviewer_script(approve_first: bool = True) -> list:
    if approve_first:
        return [
            {
                "decision": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "noteapp/core.py"},
                "rationale": "检查实现",
            },
            {
                "decision": "final",
                "output": {
                    "approved": True,
                    "summary": "实现满足验收标准",
                    "issues": [],
                    "criteria_coverage": ["AC1"],
                },
                "rationale": "通过审查",
            },
        ]
    return [
        {
            "decision": "tool_call",
            "tool": "read_file",
            "arguments": {"path": "noteapp/core.py"},
            "rationale": "检查实现",
        },
        {
            "decision": "final",
            "output": {
                "approved": False,
                "summary": "delete 未做越界检查",
                "issues": [
                    {
                        "severity": "high",
                        "file": "noteapp/core.py",
                        "line": 14,
                        "problem": "delete 未处理越界索引",
                        "suggestion": "增加 index 范围检查并抛 IndexError",
                    }
                ],
                "criteria_coverage": ["AC1 部分满足"],
            },
            "rationale": "拒绝并给出修改建议",
        },
        {
            "decision": "tool_call",
            "tool": "read_file",
            "arguments": {"path": "noteapp/core.py"},
            "rationale": "复审",
        },
        {
            "decision": "final",
            "output": {
                "approved": True,
                "summary": "越界检查已补充，满足验收标准",
                "issues": [],
                "criteria_coverage": ["AC1"],
            },
            "rationale": "复审通过",
        },
    ]


# =========================================================
# 辅助
# =========================================================


async def _start_run(app_ctx, sample_repo: Path, scripts: dict, request: str = "为 NoteStore 增加 delete 功能"):
    for agent, script in scripts.items():
        app_ctx.set_llm_script(agent, script)
    async with app_ctx.database.session() as session:
        project = await repo.create_project(session, name="noteapp", repo_path=str(sample_repo))
        run = await repo.create_run(session, project.id, request)
    manager = RunManager(app_ctx)
    await manager.start_run(run.id)
    await manager.wait(run.id)
    return manager, run.id


async def _run_row(app_ctx, run_id: str):
    async with app_ctx.database.session() as session:
        return await repo.get_run(session, run_id)


async def _events(app_ctx, run_id: str) -> list:
    async with app_ctx.database.session() as session:
        rows = await repo.list_events(session, run_id)
    return [r.type for r in rows]


def _git_log(workspace: Path) -> str:
    """完整提交日志（含正文，--oneline 只显示标题行）。"""
    proc = subprocess.run(
        ["git", "log", "--format=%B"], cwd=str(workspace), capture_output=True, text=True, encoding="utf-8"
    )
    return proc.stdout


DEFAULT_SCRIPTS = {
    "product": [REQUIREMENTS],
    "architect": [ARCHITECTURE],
    "coder": coder_script(rounds=2),
    "tester": [RUN_TEST_CALL, _tester_report(True)],
    "reviewer": reviewer_script(approve_first=True),
}


# =========================================================
# 测试
# =========================================================


class TestFullSuccessFlow:
    async def test_approve_and_commit(self, app_ctx, sample_repo):
        manager, run_id = await _start_run(app_ctx, sample_repo, DEFAULT_SCRIPTS)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"unexpected status={run.status} error={run.error}"
        assert Path(run.workspace_path).exists()

        # 任务完成
        async with app_ctx.database.session() as session:
            tasks = await repo.list_tasks(session, run_id)
        assert len(tasks) == 1 and tasks[0].status == "COMPLETED"

        # 代码已修改
        core = (Path(run.workspace_path) / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "def delete" in core
        test_file = (Path(run.workspace_path) / "tests" / "test_core.py").read_text(encoding="utf-8")
        assert "test_delete" in test_file

        # 审批（approve）→ Commit
        await manager.submit_approval(run_id, "approve", note="looks good")
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed", f"status={run.status} error={run.error}"

        # 分支上产生了提交
        assert run.branch.startswith("agent/run-")
        log = _git_log(Path(run.workspace_path))
        assert "Multi-Agent Copilot run" in log

        # 原始仓库 main 不受影响（工作区隔离）
        main_log = _git_log(sample_repo)
        assert "Multi-Agent Copilot run" not in main_log

        # 事件与指标
        types = await _events(app_ctx, run_id)
        for expected in (
            ET.RUN_STARTED.value,
            ET.SUPERVISOR_DECISION.value,
            ET.REQUIREMENTS_READY.value,
            ET.TASKS_GENERATED.value,
            ET.TASK_STARTED.value,
            ET.TASK_COMPLETED.value,
            ET.TEST_RESULT.value,
            ET.REVIEW_RESULT.value,
            ET.APPROVAL_REQUIRED.value,
            ET.APPROVAL_RECEIVED.value,
            ET.COMMIT_DONE.value,
            ET.RUN_FINISHED.value,
        ):
            assert expected in types, f"缺少事件 {expected}"

        metrics = run.metrics or {}
        assert metrics.get("task_success") is True
        assert metrics.get("tasks_completed") == 1
        assert metrics.get("retry_count", 0) == 0
        assert "cost_usd" in metrics

        # 结束事件携带“本次做了什么”摘要（AI 解说终稿）
        async with app_ctx.database.session() as session:
            rows = await repo.list_events(session, run_id)
        finished = next(r for r in rows if r.type == ET.RUN_FINISHED.value)
        summary = str(finished.data.get("summary") or "")
        assert "完成 1/1 个任务" in summary
        assert "已提交" in summary

        # 审批留痕
        async with app_ctx.database.session() as session:
            approvals = await repo.list_approvals(session, run_id)
        assert any(a.status == "approved" for a in approvals)


class TestRejectFlow:
    async def test_reject_no_commit(self, app_ctx, sample_repo):
        scripts = dict(DEFAULT_SCRIPTS)
        scripts["coder"] = coder_script(rounds=1)
        manager, run_id = await _start_run(app_ctx, sample_repo, scripts)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval"

        await manager.submit_approval(run_id, "reject", note="not acceptable")
        await manager.wait(run_id)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "rejected"

        # 拒绝路径的结束摘要说明变更未提交
        async with app_ctx.database.session() as session:
            rows = await repo.list_events(session, run_id)
        failed = next(r for r in rows if r.type == ET.RUN_FAILED.value)
        assert "人工审批拒绝" in str(failed.data.get("summary") or "")

        # 分支未产生新提交（仅初始 commit）
        log = _git_log(Path(run.workspace_path))
        assert "Multi-Agent Copilot run" not in log

        async with app_ctx.database.session() as session:
            approvals = await repo.list_approvals(session, run_id)
        assert any(a.status == "rejected" for a in approvals)


class TestSelfCorrectionLoop:
    async def test_review_reject_repair_and_review_again(self, app_ctx, sample_repo):
        scripts = {
            "product": [REQUIREMENTS],
            "architect": [ARCHITECTURE],
            "coder": coder_script(rounds=2),
            "tester": [RUN_TEST_CALL, _tester_report(True), RUN_TEST_CALL, _tester_report(True)],
            "reviewer": reviewer_script(approve_first=False),
        }
        manager, run_id = await _start_run(app_ctx, sample_repo, scripts)

        run = await _run_row(app_ctx, run_id)
        assert run.status == "waiting_approval", f"status={run.status} error={run.error}"

        # 发生了 Review 修复闭环
        types = await _events(app_ctx, run_id)
        assert ET.REPAIRING.value in types
        review_events = types.count(ET.REVIEW_RESULT.value)
        assert review_events >= 2

        # 修复后的代码包含越界检查
        core = (Path(run.workspace_path) / "noteapp" / "core.py").read_text(encoding="utf-8")
        assert "raise IndexError" in core

        # 审批通过
        await manager.submit_approval(run_id, "approve")
        await manager.wait(run_id)
        run = await _run_row(app_ctx, run_id)
        assert run.status == "completed"
        assert run.metrics.get("retry_count", 0) >= 1


class TestStateQueries:
    async def test_state_and_tasks_endpoints_data(self, app_ctx, sample_repo):
        manager, run_id = await _start_run(app_ctx, sample_repo, DEFAULT_SCRIPTS)

        # 通过 LangGraph Checkpoint 查询状态
        graph = manager._get_graph()
        snapshot = await graph.aget_state(manager._config(run_id))
        values = dict(snapshot.values or {})
        assert values.get("requirements", {}).get("summary")
        assert values.get("architecture", {}).get("tasks")
        assert values.get("test_results", {}).get("passed") is True
        assert values.get("review_results", {}).get("approved") is True
        # 大产物引用制：状态中保存文件引用
        assert values.get("artifacts", {}).get("requirements")
        assert Path(values["artifacts"]["requirements"]).exists()

        # 挂起载荷可查询
        payload = manager.get_pending_payload(run_id)
        assert payload and payload.get("type") == "approval_required"
        assert payload.get("options") == ["approve", "reject"]

        # 服务重启场景：内存载荷丢失后仍可从 Checkpoint 恢复（审批面板可展示）
        manager._pending_payloads.clear()
        recovered = await manager.get_pending_payload_async(run_id)
        assert recovered and recovered.get("type") == "approval_required"
        assert recovered.get("tasks_total") == 1
