"""事件总线：运行事件的内存分发（SSE 实时推送）。

事件同时持久化到 run_events 表（由 TraceManager 负责），SSE 断线可重放。
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from app.schemas.events import RunEvent

_QUEUE_MAX = 1000


class EventBus:
    """进程内事件分发：每个订阅者一个队列。"""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Optional[RunEvent]]]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[Optional[RunEvent]]:
        queue: asyncio.Queue[Optional[RunEvent]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[Optional[RunEvent]]) -> None:
        subs = self._subscribers.get(run_id)
        if not subs:
            return
        if queue in subs:
            subs.remove(queue)
        if not subs:
            self._subscribers.pop(run_id, None)

    def publish(self, event: RunEvent) -> None:
        for queue in list(self._subscribers.get(event.run_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者丢弃最早事件，保证不阻塞生产者
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def close(self, run_id: str) -> None:
        """运行结束：向所有订阅者推入终止哨兵。"""
        for queue in list(self._subscribers.get(run_id, [])):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def stream(self, run_id: str) -> AsyncIterator[Optional[RunEvent]]:
        queue = self.subscribe(run_id)
        try:
            while True:
                event = await queue.get()
                yield event
                if event is None:
                    break
        finally:
            self.unsubscribe(run_id, queue)


# 全局默认总线（应用生命周期内复用）
bus = EventBus()
