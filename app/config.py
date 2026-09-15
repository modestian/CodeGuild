"""全局配置（pydantic-settings，.env 驱动）。

对应需求：NFR-MAINT-02 配置化（Capability Profile、Policy、重试上限、停止条件、沙箱规格可配置）
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_name: str = "CodeGuild"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/copilot.db"

    # ---------- LLM ----------
    llm_provider: str = "openai"  # openai | anthropic | mock
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.2
    llm_timeout: float = 120.0
    llm_max_retries: int = 2
    llm_model_overrides: dict[str, str] = Field(default_factory=dict)
    mock_scripts_file: str = ""  # Mock provider 联调/演示：JSON 脚本文件（{agent: [items]}）
    model_prices: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        }
    )

    # ---------- Agent 执行循环停止条件（FR-EXEC-02） ----------
    agent_max_steps: int = 50
    agent_max_tokens: int = 200_000
    agent_max_cost_usd: float = 5.0
    agent_timeout_seconds: float = 1800.0
    agent_max_tool_failures: int = 6

    # ---------- 闭环重试上限（FR-FIX-03） ----------
    max_code_retry: int = 3
    max_test_retry: int = 3
    max_review_retry: int = 3
    max_plan_retry: int = 2

    # ---------- Supervisor（FR-SUP-08：MVP fixed，V2 dynamic） ----------
    supervisor_mode: str = "fixed"  # fixed | dynamic

    # ---------- Sandbox（FR-SB-01~05） ----------
    sandbox_mode: str = "docker"  # docker | local
    sandbox_image: str = "multi-agent-sandbox:py312"
    sandbox_cpu_limit: float = 2.0
    sandbox_memory_limit: str = "2g"
    sandbox_network: str = "none"  # none | bridge
    sandbox_timeout_seconds: int = 300
    sandbox_setup_command: str = ""

    # ---------- 目标项目命令 ----------
    test_command: str = "python -m pytest -q"
    lint_command: str = ""
    build_command: str = ""

    # ---------- 人工审批（FR-HITL-02~04） ----------
    forced_approval_tools: list[str] = Field(
        default_factory=lambda: ["git_push", "deploy", "database_migration", "merge"]
    )
    require_approval_for_edit: bool = False
    require_approval_for_delete: bool = False
    require_approval_for_commit: bool = False
    # 敏感路径模式（命中即强制人工审批：权限/配置/CI/密钥等关键文件）
    sensitive_path_patterns: list[str] = Field(
        default_factory=lambda: [
            ".env",
            "dockerfile",
            "docker-compose",
            ".github/",
            ".gitlab-ci",
            "jenkinsfile",
            "makefile",
            "permission",
            "policy",
            "config",
            ".pem",
            ".key",
            ".lock",
            "secret",
            "credential",
            "auth",
            ".npmrc",
            ".pypirc",
            "terraform",
            "k8s",
            "helm",
        ]
    )

    # ---------- 工具输出预算 ----------
    observation_max_chars: int = 6000
    context_max_tokens: int = 60_000

    # ---------- 派生目录 ----------

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.workspaces_dir, self.artifacts_dir, self.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)

    def model_for_agent(self, agent: str | None) -> str:
        """按 Agent 解析模型（NFR-SCALE-03 LLM 可替换）。"""
        if agent and agent in self.llm_model_overrides:
            return self.llm_model_overrides[agent]
        return self.llm_model

    def price_for_model(self, model: str) -> dict[str, float]:
        if model in self.model_prices:
            return self.model_prices[model]
        # 前缀匹配（如 claude-3-5-sonnet-20241022 → claude-3-5-sonnet）
        for key, price in self.model_prices.items():
            if model.startswith(key):
                return price
        return {"input": 0.0, "output": 0.0}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """测试用：重置缓存。"""
    get_settings.cache_clear()
