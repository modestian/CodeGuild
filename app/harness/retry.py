"""RetryManager：统一处理工具与模型调用的失败重试。

对应需求：FR-HARNESS-06（RetryManager 统一重试）、NFR-REL-03（防无限循环）。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")


class RetryExhausted(Exception):
    def __init__(self, attempts: int, last_error: BaseException | None):
        super().__init__(f"重试 {attempts} 次后仍失败: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


class RetryManager:
    """指数退避重试（带抖动）。"""

    def __init__(self, max_attempts: int = 3, base_delay: float = 0.5, max_delay: float = 8.0):
        self.max_attempts = max(1, max_attempts)
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        retryable: Optional[Callable[[BaseException], bool]] = None,
        on_retry: Optional[Callable[[int, BaseException], Any]] = None,
    ) -> T:
        last_error: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await fn()
            except BaseException as exc:  # noqa: BLE001 —— 明确按 retryable 判定
                if retryable is not None and not retryable(exc):
                    raise
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                delay *= 0.5 + random.random()  # 抖动
                if on_retry is not None:
                    on_retry(attempt, exc)
                await asyncio.sleep(delay)
        raise RetryExhausted(self.max_attempts, last_error)


def is_transient_error(exc: BaseException) -> bool:
    """判断是否为可重试的瞬时错误（网络/超时/限流/服务端 5xx）。"""
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connect", "ratelimit", "apiconnection", "internalserver")):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("timed out", "timeout", "connection", "rate limit", "overloaded", "try again"))
