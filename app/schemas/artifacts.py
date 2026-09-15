"""结构化软件工程产物（Artifact）。

Agent 之间通过 Structured Output + Shared State 协作（P3/P4）：
Requirements → Architecture(Task DAG) → Code Patch → Test Report → Review Report。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# =========================================================
# Product Agent 输出（FR-PROD-01~06）
# =========================================================


class Feature(BaseModel):
    id: str = Field(description="功能编号，如 F1")
    name: str
    description: str
    priority: str = Field(default="high", description="high | medium | low")


class UserStory(BaseModel):
    id: str = Field(description="用户故事编号，如 US1")
    as_a: str = Field(description="角色")
    i_want: str = Field(description="期望能力")
    so_that: str = Field(description="业务价值")
    feature_id: str = ""


class AcceptanceCriterion(BaseModel):
    id: str = Field(description="验收标准编号，如 AC1")
    description: str
    feature_id: str = ""


class NonFunctionalRequirement(BaseModel):
    id: str = Field(description="非功能需求编号，如 NFR1")
    category: str = Field(description="performance | security | reliability | compatibility | maintainability 等")
    description: str


class OpenQuestion(BaseModel):
    id: str = Field(description="问题编号，如 Q1")
    question: str
    assumption: str = Field(default="", description="在未澄清前采用的默认假设")


class Requirements(BaseModel):
    """Product Agent 结构化输出（FR-PROD-01~06）。"""

    summary: str = ""
    features: list[Feature] = Field(default_factory=list)
    user_stories: list[UserStory] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


# =========================================================
# Architect Agent 输出（FR-ARCH-01~06）
# =========================================================


class ModuleSpec(BaseModel):
    name: str
    purpose: str
    interfaces: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ApiContract(BaseModel):
    name: str
    method: str = ""
    path: str = ""
    request: str = ""
    response: str = ""
    description: str = ""


class DataModel(BaseModel):
    name: str
    fields: list[str] = Field(default_factory=list)
    description: str = ""


class TaskItem(BaseModel):
    """Task DAG 任务项（FR-ARCH-06 / FR-TASK-01）。"""

    id: str = Field(description="任务编号，如 T1")
    title: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    priority: str = "high"
    acceptance_criteria: list[str] = Field(default_factory=list)


class Architecture(BaseModel):
    """Architect Agent 结构化输出。"""

    summary: str = ""
    design_overview: str = ""
    modules: list[ModuleSpec] = Field(default_factory=list)
    api_contracts: list[ApiContract] = Field(default_factory=list)
    data_models: list[DataModel] = Field(default_factory=list)
    module_dependencies: list[str] = Field(default_factory=list, description="模块间依赖描述，如 A -> B")
    constraints: list[str] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)


# =========================================================
# Coding Agent（FR-CODE）
# =========================================================


class PlanStep(BaseModel):
    step: int
    description: str


class CodingPlan(BaseModel):
    """修改计划（FR-CODE-04：制定 Plan 后再执行修改）。"""

    task_id: str = ""
    approach: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    files_to_change: list[str] = Field(default_factory=list)
    test_strategy: str = ""


class CoderFinal(BaseModel):
    """Coding Agent 单任务结束输出。"""

    status: str = Field(description="done | blocked")
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    validation: str = Field(default="", description="验证方式与结果简述")
    notes: str = ""


# =========================================================
# Test Agent 输出（FR-TEST-06）
# =========================================================


class TestFailure(BaseModel):
    test: str
    message: str = ""
    file: str = ""
    line: Optional[int] = None


class TestSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0


class TestReport(BaseModel):
    """Test Agent 结构化结果：passed / summary / failures。"""

    passed: bool = False
    summary: TestSummary = Field(default_factory=TestSummary)
    failures: list[TestFailure] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    raw_artifact: str = Field(default="", description="原始输出保存路径（大产物引用制）")
    notes: str = ""


# =========================================================
# Reviewer Agent 输出（FR-REV-07）
# =========================================================


class ReviewIssue(BaseModel):
    severity: str = Field(description="critical | high | medium | low")
    file: str = ""
    line: Optional[int] = None
    problem: str
    suggestion: str = ""


class ReviewReport(BaseModel):
    approved: bool = False
    summary: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)
    criteria_coverage: list[str] = Field(default_factory=list)


# =========================================================
# Supervisor 决策（FR-SUP-01~09）
# =========================================================


class SupervisorDecision(BaseModel):
    """调度决策：必须包含 next_agent 与 reason。"""

    next_agent: str = Field(
        description="product | architect | development | final_review | human_approval | end"
    )
    reason: str = ""


# =========================================================
# Research Agent 输出（FR-RES-03，V2）
# =========================================================


class ResearchFinding(BaseModel):
    title: str
    detail: str
    source: str = ""


class ResearchResult(BaseModel):
    question: str
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    answer: str = ""


# =========================================================
# 意图分类（query / develop，轻量只读问答分流）
# =========================================================


class IntentDecision(BaseModel):
    """请求意图分类结果：query（只读问答/介绍）| develop（需要修改代码）。"""

    intent: str = Field(description="query | develop")
    reason: str = ""


class AnswerResult(BaseModel):
    """只读问答模式输出（query 意图，不改动代码）。"""

    markdown: str = Field(description="回答正文（中文 Markdown，简洁清晰）")
    key_points: list[str] = Field(default_factory=list, description="要点速览")
    files_referenced: list[str] = Field(default_factory=list, description="回答引用的仓库文件")


# =========================================================
# 最终报告
# =========================================================


class FinalReport(BaseModel):
    """Final Review 汇总（Main Graph: Final Review → Human Approval）。"""

    ready_for_approval: bool = False
    tasks_total: int = 0
    tasks_completed: int = 0
    tests_passed: bool = False
    review_approved: bool = False
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
    blockers: list[str] = Field(default_factory=list)
