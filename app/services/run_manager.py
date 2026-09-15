"""RunManager：运行生命周期调度（启动 / 中断 / 恢复 / 完成收尾）。

- 后台执行 LangGraph Main Graph（thread_id = run_id，Checkpoint 持久化）
- 处理 interrupt（人工审批）：记录挂起载荷、更新运行状态、推送 approval_required 事件
- 恢复：POST /runs/{id}/approve 或 /resume → Command(resume=...) 从中断点继续（NFR-REL-01）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from langgraph.types import Command

from app.graph.main_graph import build_main_graph
from app.schemas.events import EventType
from app.schemas.state import RunStatus, empty_dev_state
from app.services.app_context import AppContext
from app.storage import repositories as repo

logger = logging.getLogger("copilot.run_manager")

RECURSION_LIMIT = 300


class RunConflict(RuntimeError):
    """运行状态冲突（例如重复启动 / 非挂起状态提交审批）。"""


class RunManager:
    def __init__(self, app: AppContext):
        self.app = app
        self._tasks: dict[str, asyncio.Task] = {}
        self._graph = None
        self._pending_payloads: dict[str, dict] = {}

    # =====================================================
    # 图（带 Checkpoint，进程内单例）
    # =====================================================

    def _get_graph(self):
        if self._graph is None:
            self._graph = build_main_graph(self.app, checkpointer=self.app.saver)
        return self._graph

    def _config(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}

    # =====================================================
    # 启动
    # =====================================================

    async def start_run(self, run_id: str) -> None:
        """创建工作区并后台启动 Main Graph。"""
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
            if run is None:
                raise RunConflict(f"运行不存在: {run_id}")
            project = await repo.get_project(session, run.project_id)
        if project is None:
            raise RunConflict(f"项目不存在: {run.project_id}")

        # Mock 演示/联调：每次运行刷新脚本队列
        self.app.reload_mock_scripts()

        # 工作区隔离（FR-GIT-01/02）：独立 worktree + 分支
        ws = await self.app.workspaces.create_run_workspace(project.repo_path, project.name, run_id)
        async with self.app.database.session() as session:
            await repo.update_run(
                session,
                run_id,
                workspace_path=ws.path,
                branch=ws.branch,
                status=RunStatus.RUNNING.value,
                current_agent="system",
            )

        initial_state = empty_dev_state(run.project_id, run_id, run.request)
        initial_state["workspace_path"] = ws.path
        initial_state["branch"] = ws.branch
        # 请求模式：query（只读问答）| develop（开发闭环）| auto（LLM 意图判定）
        request_mode = str(getattr(run, "mode", "") or "auto").lower()
        initial_state["request_mode"] = request_mode if request_mode in {"query", "develop"} else "auto"

        self._spawn(run_id, inputs=initial_state)

    def _spawn(self, run_id: str, inputs: Optional[dict] = None, resume: Optional[Any] = None) -> None:
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            raise RunConflict(f"运行 {run_id} 正在执行中")
        task = asyncio.create_task(self._invoke(run_id, inputs=inputs, resume=resume))
        self._tasks[run_id] = task

    # =====================================================
    # 执行与收尾
    # =====================================================

    async def _invoke(self, run_id: str, inputs: Optional[dict], resume: Optional[Any]) -> None:
        graph = self._get_graph()
        config = self._config(run_id)
        try:
            payload: Any = Command(resume=resume) if resume is not None else inputs
            await graph.ainvoke(payload, config)
        except asyncio.CancelledError:
            # 人工取消运行：收尾并吞掉异常（任务正常结束）
            logger.info("Run cancelled by human: %s", run_id)
            await self._finalize_cancel(run_id)
            return
        except Exception as exc:  # noqa: BLE001 —— 图执行失败：标记运行失败
            logger.exception("Graph 执行异常 run=%s", run_id)
            await self.app.tracer.emit(run_id, EventType.RUN_FAILED, f"Run failed: {str(exc)[:300]}", agent="system")
            await self._set_run_fields(run_id, status=RunStatus.FAILED.value, error=str(exc)[:2000])
            self.app.controls.forget(run_id)
            self.app.tracer.close_run(run_id)
            return
        await self._after_invoke(run_id)

    async def _after_invoke(self, run_id: str) -> None:
        graph = self._get_graph()
        config = self._config(run_id)
        snapshot = await graph.aget_state(config)
        values: dict = dict(snapshot.values or {})

        if snapshot.next:  # 被中断（等待人工审批/介入/打断）
            payload = self.payload_from_snapshot(snapshot)
            self._pending_payloads[run_id] = payload
            nodes = ",".join(snapshot.next) if snapshot.next else ""
            message = payload.get("reason") or f"等待人工输入（{nodes}）"
            if payload.get("type") == "pause":
                message = "运行已暂停，可补充新需求后继续"
            await self.app.tracer.emit(
                run_id,
                EventType.APPROVAL_REQUIRED,
                message,
                agent="human",
                data=payload,
            )
            await self._set_run_fields(
                run_id,
                status=RunStatus.WAITING_APPROVAL.value,
                current_agent="human_approval" if payload.get("type") != "pause" else "human",
            )
            return

        # 图执行完毕
        self._pending_payloads.pop(run_id, None)
        self.app.approvals.forget(run_id)
        self.app.controls.forget(run_id)
        status = str(values.get("run_status") or "")
        mapped = {
            "completed": RunStatus.COMPLETED.value,
            "failed": RunStatus.FAILED.value,
            "rejected": RunStatus.REJECTED.value,
            "cancelled": RunStatus.CANCELLED.value,
        }.get(status, RunStatus.COMPLETED.value)

        # 任务终态同步
        tasks = values.get("task_dag") or []
        if tasks:
            from app.schemas.state import TaskRecord

            async with self.app.database.session() as session:
                await repo.sync_tasks(session, run_id, [TaskRecord.model_validate(t) for t in tasks])

        metrics = await self._metrics(run_id, values)
        await self._set_run_fields(
            run_id,
            status=mapped,
            current_agent=str(values.get("current_agent") or ""),
            metrics=metrics,
            error=str(values.get("fail_reason") or "")[:2000],
            finished=True,
        )
        # 运行结束摘要（AI 解说终稿）：query → 只读问答；develop → 简述本次做了什么
        summary = self._compose_summary(values, mapped)
        if mapped == RunStatus.COMPLETED.value:
            await self.app.tracer.emit(
                run_id,
                EventType.RUN_FINISHED,
                f"Run completed. cost=${metrics.get('cost_usd', 0)} tokens={metrics.get('input_tokens', 0) + metrics.get('output_tokens', 0)}",
                agent="system",
                data={**metrics, "summary": summary},
            )
        else:
            await self.app.tracer.emit(
                run_id,
                EventType.RUN_FAILED,
                f"Run ended with status={mapped}" + (f": {values.get('fail_reason', '')[:160]}" if values.get("fail_reason") else ""),
                agent="system",
                data={**metrics, "summary": summary},
            )
        self.app.tracer.close_run(run_id)

    @staticmethod
    def _compose_summary(values: dict, status: str) -> str:
        """运行结束摘要（AI 解说终稿）。

        - query（只读问答）：说明未改动代码，回答见 answer_ready 事件
        - develop（开发闭环）：简述完成情况 / 改动文件 / 测试审查 / 提交结果
        """
        answer = values.get("answer") or {}
        if isinstance(answer, dict) and str(answer.get("markdown") or "").strip():
            return "本次为只读问答，未改动任何代码；详细回答见上方「已回答你的问题」。"

        tasks = [t for t in (values.get("task_dag") or []) if isinstance(t, dict)]
        completed = [t for t in tasks if str(t.get("status")) == "COMPLETED"]
        changed = [
            str(c.get("path") or "")
            for c in (values.get("changed_files") or [])
            if isinstance(c, dict) and c.get("path")
        ]
        test_results = values.get("test_results") or {}
        review_results = values.get("review_results") or {}
        commits = values.get("commits") or []
        fail_reason = str(values.get("fail_reason") or "")

        parts: list[str] = []
        if tasks:
            titles: list[str] = []
            for t in completed[:3]:
                title = str(t.get("title") or t.get("id") or "").strip()
                if not title:
                    continue
                titles.append(title[:40] + ("…" if len(title) > 40 else ""))
            more = " 等" if len(completed) > 3 else ""
            done_txt = f"完成 {len(completed)}/{len(tasks)} 个任务"
            if titles:
                done_txt += f"（{'、'.join(titles)}{more}）"
            parts.append(done_txt)
        if changed:
            shown = "、".join(changed[:6]) + (" 等" if len(changed) > 6 else "")
            parts.append(f"改动 {len(changed)} 个文件：{shown}")
        if test_results:
            summary = test_results.get("summary") or {}
            total = int(summary.get("total", 0) or 0)
            passed = int(summary.get("passed", 0) or 0)
            if test_results.get("passed"):
                parts.append(f"测试全部通过（{passed}/{total}）" if total else "测试通过")
            else:
                parts.append("测试未通过")
        if review_results:
            parts.append("代码审查通过" if review_results.get("approved") else "代码审查未通过")
        if commits:
            branch = str(values.get("branch") or "")
            parts.append(f"变更已提交到分支 {branch}" if branch else "变更已提交")
        if status == RunStatus.REJECTED.value:
            parts.append("人工审批拒绝，变更未提交")
        if fail_reason:
            parts.append(f"未完成原因：{fail_reason[:160]}")
        if not parts:
            return ""
        head = "本次开发任务已完成：" if status == RunStatus.COMPLETED.value else "本次开发任务结束："
        return head + "；".join(parts) + "。"

    async def _metrics(self, run_id: str, values: dict) -> dict:
        async with self.app.database.session() as session:
            metrics = await repo.aggregate_metrics(session, run_id)
        # 评估指标（FR-EVAL：Task Success / Test Pass Rate / Retry / Cost 等）
        tasks = values.get("task_dag") or []
        completed = len([t for t in tasks if isinstance(t, dict) and t.get("status") == "COMPLETED"])
        test_results = values.get("test_results") or {}
        summary = test_results.get("summary") or {}
        total_tests = int(summary.get("total", 0) or 0)
        passed_tests = int(summary.get("passed", 0) or 0)
        metrics.update(
            {
                "tasks_total": len(tasks),
                "tasks_completed": completed,
                "task_success": bool(tasks) and completed == len(tasks),
                "test_pass_rate": round(passed_tests / total_tests, 4) if total_tests else None,
                "first_pass_success": not bool(values.get("retry_count")),
                "retry_count": int(values.get("retry_count") or 0),
                "retries": values.get("retries") or {},
                "routing_decisions": len(values.get("supervisor_history") or []),
                "files_changed": len(values.get("changed_files") or []),
            }
        )
        return metrics

    async def _set_run_fields(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        current_agent: Optional[str] = None,
        metrics: Optional[dict] = None,
        error: Optional[str] = None,
        finished: bool = False,
    ) -> None:
        fields: dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
        if current_agent is not None:
            fields["current_agent"] = current_agent
        if metrics is not None:
            fields["metrics"] = metrics
        if error is not None:
            fields["error"] = error
        if finished:
            from datetime import datetime, timezone

            fields["finished_at"] = datetime.now(timezone.utc)
        if fields:
            async with self.app.database.session() as session:
                await repo.update_run(session, run_id, **fields)

    # =====================================================
    # 审批 / 恢复
    # =====================================================

    @staticmethod
    def payload_from_snapshot(snapshot) -> dict:
        """从 Checkpoint 快照提取中断（审批）载荷（服务重启后内存态丢失时可恢复）。"""
        try:
            for task in snapshot.tasks or []:
                for itr in getattr(task, "interrupts", None) or []:
                    value = getattr(itr, "value", None)
                    if isinstance(value, dict):
                        return value
        except Exception:  # noqa: BLE001
            pass
        return {}

    async def get_pending_payload_async(self, run_id: str) -> Optional[dict]:
        """获取挂起载荷：优先内存，缺失时从 Checkpoint 恢复（如服务重启后）。"""
        payload = self._pending_payloads.get(run_id)
        if payload is not None:
            return payload
        try:
            snapshot = await self._get_graph().aget_state(self._config(run_id))
            if snapshot and snapshot.next:
                payload = self.payload_from_snapshot(snapshot)
                if payload:
                    self._pending_payloads[run_id] = payload
                    return payload
        except Exception:  # noqa: BLE001
            return None
        return None

    async def submit_approval(self, run_id: str, decision: str, note: str = "", by: str = "user") -> None:
        """提交人工审批结果并恢复运行（FR-HITL-05）。

        decision：approve | reject | continue（交付审批）；
        approve_once | approve_always（工具级审批：仅本次 / 本次运行内免问）。
        """
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
        if run is None:
            raise RunConflict(f"运行不存在: {run_id}")
        if run.status in {"completed", "failed", "rejected", "cancelled"}:
            raise RunConflict(f"运行已结束（{run.status}），无法提交审批")
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            raise RunConflict("运行正在执行中，无法提交审批")

        decision = decision.lower().strip()
        if decision not in {"approve", "reject", "continue", "approve_once", "approve_always", "resume"}:
            raise RunConflict(f"非法审批决定: {decision}")

        payload = self._pending_payloads.get(run_id) or {}
        if not payload and run.status in {"waiting_approval", "needs_human"}:
            # 服务重启后内存载荷丢失：从 Checkpoint 恢复（保障工具级审批留痕）
            payload = (await self.get_pending_payload_async(run_id)) or {}
        # 人工打断恢复（pause）：approve/resume/continue 均视为恢复，note 作为补充需求注入
        if payload.get("type") == "pause" and decision in {"approve", "resume", "continue"}:
            async with self.app.database.session() as session:
                record = await repo.create_approval_request(
                    session, run_id, "pause", {"decision": decision}, "LOW", "人工打断恢复"
                )
                await repo.decide_approval(session, record.id, "approved", by, note)
            await self.app.tracer.emit(
                run_id,
                EventType.APPROVAL_RECEIVED,
                "Human resumed the paused run" + (f" — {note[:120]}" if note else ""),
                agent="human",
                data={"decision": decision, "type": "pause"},
            )
            self._spawn(run_id, resume={"guidance": note, "decision": "approve", "by": by})
            return
        # 暂停后取消运行（pause + reject）：不恢复图，人工留痕后直接收尾为 cancelled
        if payload.get("type") == "pause" and decision in {"reject", "cancel"}:
            async with self.app.database.session() as session:
                record = await repo.create_approval_request(
                    session, run_id, "pause", {"decision": "reject"}, "LOW", "人工打断后取消运行"
                )
                await repo.decide_approval(session, record.id, "rejected", by, note)
            await self.app.tracer.emit(
                run_id,
                EventType.APPROVAL_RECEIVED,
                "Human cancelled the paused run" + (f" — {note[:120]}" if note else ""),
                agent="human",
                data={"decision": decision, "type": "pause"},
            )
            await self.cancel(run_id)
            return
        # 工具级审批（编辑/删除/提交等高风险工具中断）：先落库决定，再恢复
        if payload.get("type") == "tool_approval" and decision in {
            "approve",
            "reject",
            "approve_once",
            "approve_always",
        }:
            tool = str(payload.get("tool") or "")
            if tool:
                if decision == "approve_once":
                    scope = "once"
                elif decision == "approve_always":
                    scope = "always"
                else:
                    # 裸 approve/reject：交互模式视为一次性；auto 模式保持历史行为（本次运行内持续生效）
                    mode = await self.app.approvals.mode_for(run_id)
                    scope = "once" if mode == "interactive" else "always"
                await self.app.approvals.record_decision(run_id, tool, decision, note, by, scope=scope)
        else:
            # 人工交付审批留痕（FR-HITL-06）：每次决策追加独立记录，保留完整历史
            async with self.app.database.session() as session:
                record = await repo.create_approval_request(
                    session, run_id, "human_approval", {"decision": decision}, "HIGH", "人工交付审批"
                )
                await repo.decide_approval(
                    session,
                    record.id,
                    "approved" if decision in {"approve", "continue"} else "rejected",
                    by,
                    note,
                )

        await self.app.tracer.emit(
            run_id,
            EventType.APPROVAL_RECEIVED,
            f"Human decision: {decision}" + (f" — {note[:120]}" if note else ""),
            agent="human",
            data={"decision": decision, "tool": payload.get("tool"), "type": payload.get("type")},
        )
        resume_decision = "approve" if decision in {"approve_once", "approve_always"} else decision
        self._spawn(run_id, resume={"decision": resume_decision, "note": note, "by": by})

    async def resume(self, run_id: str, resume_value: Any) -> None:
        """通用恢复（携带自定义 resume 载荷）。"""
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
        if run is None:
            raise RunConflict(f"运行不存在: {run_id}")
        if run.status in {"completed", "failed", "rejected", "cancelled"}:
            raise RunConflict(f"运行已结束（{run.status}），不可恢复")
        self._spawn(run_id, resume=resume_value)

    # =====================================================
    # 审批模式 / 取消（人工介入）
    # =====================================================

    async def set_approval_mode(self, run_id: str, mode: str) -> None:
        """切换运行级审批模式（auto：仅高风险审批；interactive：关键操作逐步确认）。"""
        mode = mode.lower().strip()
        if mode not in {"auto", "interactive"}:
            raise RunConflict(f"非法审批模式: {mode}")
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
            if run is None:
                raise RunConflict(f"运行不存在: {run_id}")
            if run.status in {"completed", "failed", "rejected", "cancelled"}:
                raise RunConflict(f"运行已结束（{run.status}），不可切换审批模式")
            await repo.update_run(session, run_id, approval_mode=mode)
        self.app.approvals.set_mode(run_id, mode)
        await self.app.tracer.emit(
            run_id,
            EventType.LOG,
            f"审批模式已切换为 {'逐步确认' if mode == 'interactive' else '自动执行'}（{mode}）",
            agent="human",
            data={"approval_mode": mode},
        )

    async def cancel(self, run_id: str) -> None:
        """取消运行：打断执行中的图任务，或直接清理挂起状态（人工终止兜底）。"""
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
        if run is None:
            raise RunConflict(f"运行不存在: {run_id}")
        if run.status in {"completed", "failed", "rejected", "cancelled"}:
            raise RunConflict(f"运行已结束（{run.status}），无需取消")
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            return  # 状态收尾由 _invoke 的 CancelledError 分支完成
        await self._finalize_cancel(run_id)

    async def request_pause(self, run_id: str) -> None:
        """请求人工打断：下一个安全点（Supervisor 入口）挂起，等待恢复/补充需求。

        用户可随后通过审批端点（decision=resume，note=补充需求）恢复运行。
        """
        async with self.app.database.session() as session:
            run = await repo.get_run(session, run_id)
        if run is None:
            raise RunConflict(f"运行不存在: {run_id}")
        if run.status in {"completed", "failed", "rejected", "cancelled"}:
            raise RunConflict(f"运行已结束（{run.status}），无法打断")
        if run.status in {"waiting_approval", "needs_human"}:
            raise RunConflict("运行当前正在等待人工输入，无需打断")
        task = self._tasks.get(run_id)
        if task is None or task.done():
            raise RunConflict("运行未在执行中，无法打断")
        self.app.controls.request_pause(run_id)
        await self.app.tracer.emit(
            run_id,
            EventType.PAUSE_REQUESTED,
            "已收到用户打断请求，将在下一个安全点（Supervisor 调度前）暂停，可在恢复时补充新需求",
            agent="human",
        )

    async def _finalize_cancel(self, run_id: str) -> None:
        """运行取消的统一收尾：清挂起载荷、标记状态、发事件、释放资源。"""
        self._pending_payloads.pop(run_id, None)
        self.app.approvals.forget(run_id)
        self.app.controls.forget(run_id)
        await self._set_run_fields(run_id, status=RunStatus.CANCELLED.value, finished=True)
        await self.app.tracer.emit(
            run_id, EventType.RUN_CANCELLED, "Run cancelled by human", agent="human"
        )
        self.app.tracer.close_run(run_id)

    def get_pending_payload(self, run_id: str) -> Optional[dict]:
        return self._pending_payloads.get(run_id)

    def is_running(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def wait(self, run_id: str) -> None:
        """等待当前后台任务完成（测试用）。"""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
