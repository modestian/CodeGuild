"""RunControl：运行级外部控制（人工打断/暂停请求）。

机制（HITL 增强）：
- 用户随时可请求"打断"：在内存中登记暂停标志
- 图在下一个安全点（Supervisor 调度入口）检测到标志后调用 interrupt() 挂起
- 用户恢复时携带可选补充需求（guidance），恢复后注入 Agent 上下文
- 服务重启后暂停请求丢失（可接受：打断是即时交互）
"""
from __future__ import annotations


class RunControl:
    """运行级人工控制标志管理（进程内，轻量）。"""

    def __init__(self) -> None:
        self._pause: set[str] = set()

    def request_pause(self, run_id: str) -> None:
        """登记打断请求（将在下一个安全点生效）。"""
        self._pause.add(run_id)

    def pause_requested(self, run_id: str) -> bool:
        return run_id in self._pause

    def clear_pause(self, run_id: str) -> None:
        """清除打断标志（在 interrupt 恢复点调用，保证 replay 幂等）。"""
        self._pause.discard(run_id)

    def forget(self, run_id: str) -> None:
        """运行结束时清理。"""
        self._pause.discard(run_id)
