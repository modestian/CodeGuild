"""运行事件（SSE 事件流协议）。

对应需求：FR-SSE-01~03（客户端通过 SSE 接收运行事件流）、IR-10。
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    INTENT_DECIDED = "intent_decided"
    SUPERVISOR_ANALYZING = "supervisor_analyzing"
    SUPERVISOR_DECISION = "supervisor_decision"
    REQUIREMENTS_READY = "requirements_ready"
    ARCHITECTURE_READY = "architecture_ready"
    TASKS_GENERATED = "tasks_generated"
    ANSWER_READY = "answer_ready"
    TASK_READY = "task_ready"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    PLAN_UPDATED = "plan_updated"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEST_STARTED = "test_started"
    TEST_RESULT = "test_result"
    VALIDATION_RESULT = "validation_result"
    REPAIRING = "repairing"
    REVIEW_STARTED = "review_started"
    REVIEW_RESULT = "review_result"
    DIFF_READY = "diff_ready"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RECEIVED = "approval_received"
    PAUSE_REQUESTED = "pause_requested"
    PAUSE_RESUMED = "pause_resumed"
    GUIDANCE_RECEIVED = "guidance_received"
    GUIDANCE_APPLIED = "guidance_applied"
    COMMIT_DONE = "commit_done"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    ERROR = "error"
    LOG = "log"


class RunEvent(BaseModel):
    """单条运行事件。message 用于人类可读展示（如 "52 tests passed."）。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    run_id: str = ""
    seq: int = 0
    type: EventType = EventType.LOG
    agent: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)

    def sse(self) -> str:
        """SSE 帧格式。"""
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"
