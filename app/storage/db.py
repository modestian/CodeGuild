"""数据库引擎与会话管理（SQLite 默认 / PostgreSQL 可配置切换）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.storage.models import Base


class Database:
    """异步数据库封装。"""

    def __init__(self, url: str, echo: bool = False):
        self.url = url
        self._ensure_sqlite_dir(url)
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    @staticmethod
    def _ensure_sqlite_dir(url: str) -> None:
        if url.startswith("sqlite"):
            # sqlite+aiosqlite:///./data/copilot.db
            raw = url.split("///", 1)[-1]
            if raw and raw != ":memory:":
                Path(raw).parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await self._migrate()

    async def _migrate(self) -> None:
        """轻量迁移：为已有表补充新增列（SQLite 专用；PG 场景建议使用正式迁移工具）。"""
        if not self.url.startswith("sqlite"):
            return
        wanted_columns: list[tuple[str, str, str]] = [
            # (表, 列, 建列 DDL 片段)
            ("runs", "approval_mode", "approval_mode VARCHAR(16) DEFAULT 'auto'"),
            ("approvals", "scope", "scope VARCHAR(16) DEFAULT 'once'"),
            ("approvals", "consumed", "consumed BOOLEAN DEFAULT 0"),
        ]
        async with self.engine.begin() as conn:
            for table, column, ddl in wanted_columns:
                rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
                if not rows:
                    continue  # 表不存在：create_all 已负责创建（含新列）
                existing = {str(row[1]) for row in rows}
                if column not in existing:
                    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


_db: Optional[Database] = None


def set_database(db: Database) -> None:
    global _db
    _db = db


def get_database() -> Database:
    if _db is None:
        raise RuntimeError("Database 尚未初始化，请先调用 set_database()")
    return _db
