"""AppContext：Harness 全组件装配（FR-HARNESS-02）。

所有 Agent 共用同一 AgentRuntime 与组件实例，不为每个 Agent 重复实现（FR-HARNESS-01）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from app.config import Settings, get_settings
from app.harness.approval import ApprovalManager
from app.harness.context import ContextManager
from app.harness.control import RunControl
from app.harness.executor import ToolExecutor
from app.harness.guidance import GuidanceManager
from app.harness.llm import LLMClient, create_llm_client
from app.harness.observation import ObservationAdapter
from app.harness.permission import PermissionManager
from app.harness.policy import PolicyEngine
from app.harness.registry import ToolContext, ToolRegistry
from app.harness.retry import RetryManager
from app.harness.runtime import AgentRuntime
from app.harness.session import RuntimeSession, SessionStore
from app.observability import events as obs_events
from app.observability.tracing import TraceManager
from app.sandbox.docker import create_sandbox
from app.storage.db import Database, set_database
from app.tools import register_all_tools
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger("copilot.context")


class AppContext:
    """全局应用上下文（进程单例）。"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        # 存储
        self.database = Database(self.settings.database_url)
        set_database(self.database)
        # 可观测性
        self.bus = obs_events.bus
        self.tracer = TraceManager(self.database, self.settings, self.bus)
        # Harness
        self.permissions = PermissionManager()
        self.policy = PolicyEngine(self.settings, self.permissions)
        self.registry = ToolRegistry()
        register_all_tools(self.registry)
        self.sandbox = create_sandbox(self.settings)
        self.approvals = ApprovalManager(self.database, self.settings)
        self.executor = ToolExecutor(
            settings=self.settings,
            registry=self.registry,
            policy=self.policy,
            approvals=self.approvals,
            tracer=self.tracer,
            retry=RetryManager(max_attempts=2, base_delay=0.3),
        )
        self.context_manager = ContextManager(self.settings)
        self.observation = ObservationAdapter(self.settings.observation_max_chars)
        self.sessions = SessionStore(self.settings.sessions_dir)
        self.guidance = GuidanceManager(self.database)  # 运行中人工补充要求（追加需求）
        self.controls = RunControl()  # 人工打断（pause/resume）控制
        self.runtime = AgentRuntime(
            settings=self.settings,
            executor=self.executor,
            context_manager=self.context_manager,
            observation=self.observation,
            permissions=self.permissions,
            tracer=self.tracer,
            session_store=self.sessions,
            llm_factory=self._llm_factory,
            registry=self.registry,
            guidance=self.guidance,
        )
        # Workspace
        self.workspaces = WorkspaceManager(self.settings)
        # Checkpoint（FR-CKPT：关键节点保存 State，故障可恢复）
        self.saver = None
        self._saver_cm = None
        # 测试脚本注入（Mock provider 场景）
        self._llm_scripts: dict[str, list[Any]] = {}

    # =====================================================
    # 生命周期
    # =====================================================

    async def init(self) -> None:
        self.settings.ensure_dirs()
        await self.database.init()
        await self._init_saver()
        self._load_mock_scripts()

    def _load_mock_scripts(self) -> None:
        """Mock provider 演示/联调：从 mock_scripts_file 加载各 Agent 脚本队列。"""
        if self.settings.llm_provider.lower() != "mock" or not self.settings.mock_scripts_file:
            return
        import json

        path = Path(self.settings.mock_scripts_file)
        if not path.exists():
            logger.warning("mock_scripts_file 不存在: %s", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("mock_scripts_file 解析失败: %s", path, exc_info=True)
            return
        for agent, script in data.items():
            if isinstance(script, list):
                self.set_llm_script(agent, script)
        logger.info("已加载 Mock 脚本：%s", ", ".join(sorted(data.keys())))

    def reload_mock_scripts(self) -> None:
        """运行启动时刷新 Mock 脚本队列（演示/联调场景可重复运行）。"""
        self._load_mock_scripts()

    async def _init_saver(self) -> None:
        """初始化 LangGraph Checkpointer：SQLite 持久化，失败时回退内存。"""
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            db_path = self.settings.data_dir / "checkpoints.sqlite"
            self._saver_cm = AsyncSqliteSaver.from_conn_string(str(db_path))
            self.saver = await self._saver_cm.__aenter__()
        except Exception:  # noqa: BLE001 —— 回退内存 Checkpointer
            logger.warning("AsyncSqliteSaver 不可用，回退 InMemorySaver", exc_info=True)
            from langgraph.checkpoint.memory import InMemorySaver

            self.saver = InMemorySaver()

    async def close(self) -> None:
        if self._saver_cm is not None:
            try:
                await self._saver_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self._saver_cm = None
        await self.database.dispose()

    # =====================================================
    # LLM
    # =====================================================

    def _llm_factory(self, agent: str) -> LLMClient:
        # Mock provider 场景下共享脚本队列（顺序消费）
        script = self._llm_scripts.get(agent)
        return create_llm_client(self.settings, agent, script=script)

    def set_llm_script(self, agent: str, script: list[Any]) -> None:
        """测试/演示用：为指定 Agent 注入 Mock 响应脚本。"""
        self._llm_scripts[agent] = list(script)

    # =====================================================
    # 工具上下文工厂
    # =====================================================

    def make_ctx_factory(
        self,
        *,
        run_id: str,
        project_id: str,
        agent: str,
        workspace: Path,
    ) -> Callable[[RuntimeSession], ToolContext]:
        def factory(session: RuntimeSession) -> ToolContext:
            def emit(event_type: str, message: str, data: Optional[dict] = None) -> None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                loop.create_task(
                    self.tracer.emit(run_id, self._to_event_type(event_type), message, agent=agent, data=data or {})
                )

            return ToolContext(
                run_id=run_id,
                project_id=project_id,
                agent=agent,
                workspace=workspace,
                session=session,
                settings=self.settings,
                sandbox=self.sandbox,
                artifacts_dir=self.settings.artifacts_dir / run_id,
                emit=emit,
            )

        return factory

    @staticmethod
    def _to_event_type(name: str):
        from app.schemas.events import EventType

        try:
            return EventType(name)
        except ValueError:
            return EventType.LOG

    # =====================================================
    # 工件持久化（大产物引用制，FR-STATE-03）
    # =====================================================

    def save_artifact(self, run_id: str, name: str, payload: dict) -> str:
        import json

        directory = self.settings.artifacts_dir / run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def run_artifact_path(self, run_id: str, name: str) -> Path:
        return self.settings.artifacts_dir / run_id / f"{name}.json"
