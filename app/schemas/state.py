"""共享状态（DevState）与任务模型。

对应需求：FR-STATE-01~05（统一状态结构 / 字段完整 / 大产物引用制 / 防膨胀 / 状态驱动协作）、
FR-TASK-01/02（任务结构与状态机）。
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态机（FR-TASK-02）。"""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    NEEDS_HUMAN = "needs_human"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRecord(BaseModel):
    """任务记录（FR-TASK-01：id/title/dependencies/status/assigned_agent/priority）。"""

    id: str
    title: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: Optional[str] = None
    priority: str = "high"
    acceptance_criteria: list[str] = Field(default_factory=list)
    attempts: int = 0
    result_summary: str = ""
    error: str = ""


class DevState(TypedDict, total=False):
    """LangGraph 共享状态（DR-01 ~ DR-17 + 运行时扩展字段）。

    大型产物只保存引用（artifact_id / file_path），避免无限增长（FR-STATE-03/04）。
    """

    # ---- DR-01 ~ DR-17 ----
    project_id: str
    user_request: str
    requirements: dict  # DR-03
    architecture: dict  # DR-04
    task_dag: list  # DR-05（序列化的 TaskRecord 列表）
    ready_tasks: list  # DR-06（任务 id 列表）
    current_tasks: list  # DR-07
    completed_tasks: list  # DR-08
    changed_files: list  # DR-09（[{path, action, task_id}]）
    commits: list  # DR-10（[{sha, branch, message}]）
    test_results: dict  # DR-11
    review_results: dict  # DR-12
    current_agent: str  # DR-13
    iteration: int  # DR-14
    retry_count: int  # DR-15（总重试数）
    errors: list  # DR-16（节点内读改写，避免子图 reducer 双写）
    run_status: str  # DR-17

    # ---- 运行时扩展（结构化小数据 / 引用） ----
    run_id: str
    workspace_path: str
    branch: str
    request_mode: str  # 用户指定运行模式：auto | develop | query（只读问答）
    request_intent: str  # 意图分类结果：develop（开发闭环）| query（只读回答）
    answer: dict  # query 模式的只读回答（markdown / key_points / files_referenced）
    route: str  # Supervisor 路由目标（供 Conditional Edge 读取）
    supervisor_reason: str
    supervisor_history: list  # [{iteration, next_agent, reason}]
    retries: dict  # 分闭环重试计数 {code, test, review, plan}
    open_questions: list
    plan: dict  # 当前 Coding Plan
    plan_recorded: bool
    active_task_id: str  # 当前正在编码的任务
    pending_approvals: list  # 等待人工审批的工具调用
    approval: dict  # 人工审批结果
    validation: dict  # 最近一次验证结果（编码子图内）
    final_report: dict  # Final Review 汇总
    artifacts: dict  # 大产物引用 {name: file_path}
    dev_cycle_done: bool  # 开发子图是否已完成（供 Main Graph 判断）
    needs_human: bool  # 是否需要人工介入（重试超限等）
    fail_reason: str
    metrics: dict  # 运行指标缓存
    scratch: dict  # 子图内部暂存（检索上下文 / 修复反馈 / 编码结果）


def empty_dev_state(project_id: str, run_id: str, user_request: str) -> DevState:
    """构造初始 DevState。"""
    return DevState(
        project_id=project_id,
        run_id=run_id,
        user_request=user_request,
        requirements={},
        architecture={},
        task_dag=[],
        ready_tasks=[],
        current_tasks=[],
        completed_tasks=[],
        changed_files=[],
        commits=[],
        test_results={},
        review_results={},
        current_agent="",
        iteration=0,
        retry_count=0,
        errors=[],
        run_status=RunStatus.CREATED.value,
        workspace_path="",
        branch="",
        request_mode="auto",
        request_intent="",
        answer={},
        route="",
        supervisor_reason="",
        supervisor_history=[],
        retries={"code": 0, "test": 0, "review": 0, "plan": 0},
        open_questions=[],
        plan={},
        plan_recorded=False,
        active_task_id="",
        pending_approvals=[],
        approval={},
        validation={},
        final_report={},
        artifacts={},
        dev_cycle_done=False,
        needs_human=False,
        fail_reason="",
        metrics={},
        scratch={},
    )


# =========================================================
# Task DAG 工具函数（FR-ARCH-06 无环校验 / FR-TASK-04 就绪判定 / FR-TASK-06 阻塞传播）
# =========================================================


class TaskDAGError(ValueError):
    pass


def validate_task_dag(tasks: list[TaskRecord] | list[dict]) -> list[TaskRecord]:
    """校验任务 DAG：id 唯一、依赖存在、无环。返回 TaskRecord 列表。"""
    records = [t if isinstance(t, TaskRecord) else TaskRecord.model_validate(t) for t in tasks]
    ids = [t.id for t in records]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise TaskDAGError(f"任务 id 重复: {dupes}")
    id_set = set(ids)
    for t in records:
        for dep in t.dependencies:
            if dep not in id_set:
                raise TaskDAGError(f"任务 {t.id} 依赖不存在的任务 {dep}")
            if dep == t.id:
                raise TaskDAGError(f"任务 {t.id} 依赖自身")
    # 环检测（DFS）
    graph = {t.id: list(t.dependencies) for t in records}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise TaskDAGError(f"任务 DAG 存在循环依赖，涉及 {node}")
        visiting.add(node)
        for dep in graph.get(node, []):
            dfs(dep)
        visiting.discard(node)
        visited.add(node)

    for t in records:
        dfs(t.id)
    return records


def compute_ready_tasks(tasks: list[TaskRecord] | list[dict]) -> list[str]:
    """就绪判定（FR-TASK-04）：依赖全部 COMPLETED 且自身 PENDING/READY 的任务进入 READY。"""
    records = [t if isinstance(t, TaskRecord) else TaskRecord.model_validate(t) for t in tasks]
    by_id = {t.id: t for t in records}
    ready: list[str] = []
    for t in records:
        if t.status in (TaskStatus.PENDING, TaskStatus.READY):
            if all(
                by_id[d].status == TaskStatus.COMPLETED for d in t.dependencies if d in by_id
            ):
                ready.append(t.id)
    return ready


def propagate_blocking(tasks: list[TaskRecord] | list[dict]) -> list[TaskRecord]:
    """阻塞传播（FR-TASK-06）：依赖链路上出现 FAILED/BLOCKED 的任务进入 BLOCKED。"""
    records = [t if isinstance(t, TaskRecord) else TaskRecord.model_validate(t) for t in tasks]
    by_id = {t.id: t for t in records}
    changed = True
    while changed:
        changed = False
        for t in records:
            if t.status in (TaskStatus.BLOCKED, TaskStatus.COMPLETED, TaskStatus.FAILED):
                continue
            for dep in t.dependencies:
                d = by_id.get(dep)
                if d and d.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                    t.status = TaskStatus.BLOCKED
                    changed = True
                    break
    return records


def topological_order(tasks: list[TaskRecord] | list[dict]) -> list[str]:
    """拓扑序（MVP 顺序执行的调度依据）。"""
    records = validate_task_dag(tasks)
    by_id = {t.id: t for t in records}
    result: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        for dep in by_id[node].dependencies:
            visit(dep)
        result.append(node)

    for t in records:
        visit(t.id)
    return result


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"
