"""GuidanceManager：运行中人工补充要求（追加需求）管理。

- 用户在运行进行中提交补充要求（不打断执行）
- Agent 执行循环在下一步（待办工具调用排空后）自动领取并注入 LLM 上下文
- 领取即消费（consumed），避免重复注入；服务重启后仍可从 DB 领取未消费项
"""
from __future__ import annotations

from typing import Any

from app.storage import repositories as repo
from app.storage.db import Database


class GuidanceManager:
    """补充要求的登记与领取（DB 持久化，多进程安全依赖消费标记）。"""

    def __init__(self, database: Database):
        self.database = database

    async def add(self, run_id: str, text: str, source: str = "user") -> dict[str, Any]:
        """登记一条补充要求（status=pending，等待执行循环领取）。"""
        async with self.database.session() as session:
            row = await repo.create_guidance(session, run_id, text, source)
            return {
                "id": row.id,
                "text": row.text,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

    async def drain(self, run_id: str) -> list[dict[str, Any]]:
        """领取全部未消费的补充要求并标记消费（供执行循环注入）。"""
        async with self.database.session() as session:
            rows = await repo.list_guidance(session, run_id, status="pending")
            if not rows:
                return []
            items = [
                {
                    "id": row.id,
                    "text": row.text,
                    "source": row.source,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
            await repo.consume_guidance(session, [row.id for row in rows])
            return items

    async def list(self, run_id: str) -> list[dict[str, Any]]:
        """全部补充要求（含已消费，供前端展示与审计）。"""
        async with self.database.session() as session:
            rows = await repo.list_guidance(session, run_id)
            return [
                {
                    "id": row.id,
                    "text": row.text,
                    "source": row.source,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
                }
                for row in rows
            ]
