# 基于 LangGraph 的多 Agent 软件开发系统设计方案

| 项目 | 内容 |
|------|------|
| 文档版本 | V2.0 |
| 文档状态 | 设计稿 |
| 更新时间 | 2026-09-13 |
| 项目定位 | 面向真实代码仓库的 Multi-Agent Software Engineering Platform |

---

# 1. 项目概述

## 1.1 项目名称

**Multi-Agent Software Development Copilot**

基于 **LangGraph + Agent Harness + Code RAG** 的多 Agent 协作软件开发平台。

---

## 1.2 项目目标

本项目旨在构建一个能够围绕真实代码仓库持续执行软件开发任务的多 Agent 系统。

用户输入自然语言开发需求后，系统能够自动完成：

- 需求分析
- 技术方案设计
- 开发任务拆分
- 代码仓库理解
- 代码修改
- 自动化测试
- Code Review
- Bug 修复
- Git Diff 生成
- 人工审批
- Git Commit / PR

系统不是简单地让多个 LLM 按固定顺序生成文本，而是构建：

> **基于共享状态、任务依赖、动态调度、工具执行和反馈闭环的 Agent 软件工程系统。**

---

# 2. 核心设计原则

系统遵循以下原则。

## 2.1 Orchestration 与 Execution 分离

明确区分三个层次：

```text
LangGraph
    ↓
决定“哪个 Agent 工作”

Agent
    ↓
决定“当前应该做什么”

Harness
    ↓
负责“如何安全、稳定地执行”
```

其中：

- **LangGraph**：负责多 Agent 编排、状态流转、条件路由和恢复。
- **Agent**：负责推理、规划和动作选择。
- **Harness**：负责上下文、工具、权限、执行环境和 Observation。

---

## 2.2 Agent 专业化

每个 Agent 只负责明确的软件工程职责。

不设计“什么都能做”的万能 Agent。

---

## 2.3 State-driven Collaboration

Agent 之间不依赖自由聊天完成协作。

核心协作方式为：

```text
Agent A
   ↓
Structured Output
   ↓
Shared State
   ↓
Agent B
```

---

## 2.4 Artifact-driven Collaboration

Agent 之间主要传递结构化软件工程产物：

```text
User Requirement
      ↓
Requirements
      ↓
Architecture
      ↓
Task DAG
      ↓
Code Patch
      ↓
Test Report
      ↓
Review Report
```

---

## 2.5 闭环优先

系统必须形成：

```text
Code
 ↓
Test
 ↓
Review
 ↓
Fix
 ↓
Test
```

而不是：

```text
Generate Code
 ↓
END
```

---

## 2.6 Least Privilege

不同 Agent 拥有不同工具和权限。

例如 Reviewer 默认只能读取代码，不能修改代码。

---

## 2.7 Safe Execution

所有可能执行用户代码或 Agent 生成代码的操作均在 Sandbox 中运行。

---

# 3. 总体系统架构

```text
                         User
                           │
                           ▼
                ┌────────────────────┐
                │      API Layer     │
                │ FastAPI / SSE      │
                └─────────┬──────────┘
                          │
                          ▼

════════════════ Orchestration Layer ════════════════

                    LangGraph
                        │
                  Shared State
                        │
                    Supervisor
                        │
       ┌────────────────┼────────────────┐
       │                │                │
       ▼                ▼                ▼
 Product Agent    Architect Agent   Research Agent
       │                │                │
       └────────────────┼────────────────┘
                        │
                     Task DAG
                        │
              Task Scheduler
                 /            \
                ▼              ▼
          Coding Agent     Coding Agent
                │              │
                └──────┬───────┘
                       ▼
                Integration Agent
                       │
                       ▼
                  Test Agent
                       │
                  tests pass?
                  /          \
                NO            YES
                │              │
                ▼              ▼
          Coding Agent    Reviewer Agent
                ▲              │
                │          approved?
                │           /      \
                └──── NO ◄─        YES
                                  │
                                  ▼
                           Human Approval
                                  │
                                  ▼
                             Git Commit

══════════════════ Agent Layer ══════════════════════

              Role / Goal / Prompt
                        │
                        ▼

═════════════════ Harness Layer ═════════════════════

               Unified Agent Runtime
                        │
       ┌────────────────┼────────────────┐
       ▼                ▼                ▼
 Context Manager   Tool Runtime      Policy Engine
       │                │                │
       ▼                ▼                ▼
 Memory/RAG      Tool Registry     Permissions
                        │
                  Tool Executor
                        │
                 Sandbox Manager
                        │
           ┌────────────┼─────────────┐
           ▼            ▼             ▼
       Filesystem      Git           Shell
           │            │             │
           └────────────┼─────────────┘
                        ▼
                 Docker Sandbox

════════════════ Infrastructure Layer ═══════════════

 PostgreSQL / Redis / Vector DB / Git / Docker
       LangSmith / OpenTelemetry / Metrics
```

---

# 4. Agent 角色设计

MVP 阶段仅保留必要 Agent。

## 4.1 Supervisor Agent

Supervisor 是系统的中央协调 Agent。

## 职责

- 判断当前项目状态
- 选择下一执行 Agent
- 处理 Agent 执行结果
- 识别任务阻塞
- 控制重试
- 判断是否需要重新规划
- 判断是否需要人工介入
- 判断任务是否结束

Supervisor 原则上：

> **不直接写代码，不执行具体开发任务。**

## 示例

当前状态：

```json
{
  "requirements_ready": true,
  "architecture_ready": true,
  "code_changed": true,
  "tests_passed": false
}
```

Supervisor：

```json
{
  "next_agent": "coding_agent",
  "reason": "test failures require code repair"
}
```

---

# 5. Product Agent

负责将自然语言需求转化为结构化产品需求。

## 输入

```text
用户需求
现有项目背景
项目约束
```

## 输出

```json
{
  "features": [],
  "user_stories": [],
  "acceptance_criteria": [],
  "non_functional_requirements": [],
  "open_questions": []
}
```

## 职责

- Feature 拆分
- 用户故事
- 验收标准
- 非功能需求
- 需求冲突发现
- 需求缺失发现

---

# 6. Architect Agent

负责把产品需求转化为技术设计。

## 输出内容

- 技术方案
- 模块划分
- API 契约
- 数据模型
- 模块依赖
- Task DAG

示例：

```json
{
  "tasks": [
    {
      "id": "T1",
      "title": "Create User Model",
      "depends_on": []
    },
    {
      "id": "T2",
      "title": "Implement JWT Authentication",
      "depends_on": ["T1"]
    }
  ]
}
```

---

# 7. Task DAG

开发任务使用 DAG 表达，而不是简单列表。

```text
T1 User Model ──→ T2 JWT Auth ───────┐
                                      │
T3 Article Model ─────────────────────┼──→ T4 Article API
                                      │
                                      └──→ T5 Comment API
```

任务结构：

```json
{
  "id": "T4",
  "title": "Implement Article API",
  "dependencies": ["T2", "T3"],
  "status": "pending",
  "assigned_agent": null,
  "priority": "high"
}
```

状态：

```text
PENDING
READY
RUNNING
BLOCKED
REVIEWING
COMPLETED
FAILED
```

Task Scheduler 根据依赖关系确定：

```text
READY TASKS
```

无依赖关系的任务可以并行执行。

---

# 8. Coding Agent

Coding Agent 负责真实代码修改。

其工作流不是：

```text
Task
 ↓
Generate Code
```

而是：

```text
Task
 ↓
Repository Exploration
 ↓
Code Retrieval
 ↓
Read Relevant Files
 ↓
Plan
 ↓
Edit
 ↓
Run Validation
 ↓
Inspect Result
 ↓
Fix / Finish
```

Coding Agent 是整个系统中最典型的：

> **LLM + Harness**

Agent 负责决定：

```text
下一步应该做什么
```

Harness 负责：

```text
实际如何执行
```

---

# 9. Unified Agent Harness

系统不为每个 Agent 重复实现 Harness。

统一提供：

```text
AgentRuntime
│
├── ContextManager
├── ToolRegistry
├── ToolExecutor
├── PolicyEngine
├── PermissionManager
├── ApprovalManager
├── GuardrailManager
├── SandboxManager
├── ObservationAdapter
├── RetryManager
├── StateManager
└── TraceManager
```

---

# 10. Context Manager

负责为每次模型调用构造最必要的上下文。

例如 Coding Agent 当前任务：

```text
修复 JWT expiration validation
```

不会把整个代码库放入 Prompt。

实际上下文：

```text
System Prompt
+
Current Task
+
Acceptance Criteria
+
Architecture Constraints
+
Relevant Code Chunks
+
Recent Tool Results
+
Current Errors
```

核心原则：

> **只给模型完成当前任务所需的信息。**

V2 起由 ContextManager 进一步提供（见第 45 节）：

```text
Compaction
（超阈值摘要压缩，保留决策与结论）

Sub-Agent Context Isolation
（子 Agent 独立上下文，仅接收任务切片）

Dynamic Assembly
（按任务动态拼装上下文）
```

---

# 11. Tool Registry

统一注册系统可用工具。

## Filesystem

```text
list_files
read_file
search_code
grep
read_symbol
edit_file
create_file
apply_patch
```

## Git

```text
git_status
git_diff
git_log
git_branch
git_commit
```

## Execution

```text
run_command
run_test
run_linter
run_build
```

## Retrieval

```text
retrieve_code
search_docs
search_history
```

## External

```text
github
jira
web_search
documentation
```

外部能力优先通过 MCP 接入。

---

# 12. Tool Definition

每个 Tool 至少包含：

```text
name
description
input_schema
output_schema
risk_level
timeout
required_permission
```

例如：

```json
{
  "name": "edit_file",
  "risk_level": "MEDIUM",
  "timeout": 30,
  "permission": "workspace_write"
}
```

---

# 13. Capability Profile

所有 Agent 共用 Harness，但拥有不同 Capability Profile。

## Coding Agent

```yaml
tools:
  - read_file
  - search_code
  - edit_file
  - apply_patch
  - run_test
  - git_diff

workspace: read_write

shell: sandbox_only

max_steps: 50
```

## Test Agent

```yaml
tools:
  - read_file
  - run_test
  - run_linter
  - run_build

workspace: read_only

source_edit: deny

max_steps: 20
```

## Reviewer Agent

```yaml
tools:
  - read_file
  - search_code
  - git_diff
  - run_test

workspace: read_only

edit_file: deny

max_steps: 15
```

这样实现：

> **统一 Runtime + 不同权限配置。**

---

# 14. Policy Engine

工具真正执行前经过：

```text
Tool Call
   ↓
Schema Validation
   ↓
Policy Validation
   ↓
Permission Check
   ↓
Risk Evaluation
   ↓
Execute / Approval / Reject
```

风险等级：

```text
LOW
MEDIUM
HIGH
CRITICAL
```

例如：

| Action | Risk |
|---|---|
| read_file | LOW |
| search_code | LOW |
| edit_file | MEDIUM |
| run_test | MEDIUM |
| delete_file | HIGH |
| git_commit | HIGH |
| git_push | CRITICAL |
| deploy | CRITICAL |
| database migration | CRITICAL |

Guardrails 与 Policy Engine 分工（V2，见第 45 节）：

```text
Policy Engine → 权限、风险等级、审批决策
Guardrails    → 语义级安全检测
（Prompt Injection / 敏感信息 / 越权指令）
```

---

# 15. Human-in-the-loop

对于高风险操作：

```text
Agent
 ↓
Tool Call
 ↓
Policy Engine
 ↓
Approval Required
 ↓
LangGraph interrupt()
 ↓
Human
 /   \
YES   NO
 ↓     ↓
Run   Reject
```

建议策略：

## 自动允许

```text
read_file
search_code
git_diff
run_test
run_linter
```

## 可配置审批

```text
edit_file
delete_file
git_commit
```

## 强制审批

```text
git_push
merge
deploy
database migration
production operation
```

---

# 16. Sandbox

所有代码执行必须运行在隔离环境。

结构：

```text
Agent
 ↓
Harness
 ↓
Sandbox Manager
 ↓
Docker Container
 ↓
Command / Test / Build
```

Sandbox 负责：

- CPU 限制
- 内存限制
- 执行超时
- 文件系统隔离
- 网络权限
- Environment Variables
- Secret Isolation

默认禁止访问：

```text
Host filesystem
Host SSH Key
Production DB
Cloud Credentials
Private Environment Variables
```

---

# 17. Observation Adapter

Tool 原始结果不直接全部交给模型。

例如 pytest 原始输出可能有：

```text
8000 lines
```

Observation Adapter 转为：

```json
{
  "status": "failed",
  "passed": 127,
  "failed": 2,
  "errors": [
    {
      "test": "test_invalid_token",
      "message": "expected 401 but received 500"
    }
  ]
}
```

其职责：

- 日志截断
- 错误摘要
- Structured Output
- 敏感信息过滤
- 重复信息消除
- Token 压缩

---

# 18. Agent Execution Loop

单 Agent 内部执行：

```text
Build Context
      ↓
Model Call
      ↓
Decision
   /       \
Final     Tool Call
            ↓
       Policy Check
            ↓
       Tool Executor
            ↓
        Observation
            ↓
       Update State
            ↓
        Model Call
```

必须设置停止条件：

```text
max_steps
max_tokens
max_cost
timeout
max_tool_failures
```

避免无限 Agent Loop。

---

# 19. Test Agent

Test Agent 独立于 Coding Agent。

主要负责：

- Unit Test
- Integration Test
- Build
- Lint
- Static Analysis
- Test Result Analysis

输出：

```json
{
  "passed": false,
  "summary": {
    "total": 52,
    "passed": 49,
    "failed": 3
  },
  "failures": []
}
```

---

# 20. Reviewer Agent

Reviewer 不负责验证程序能否运行，而负责：

```text
实现是否正确？
```

检查：

- 是否满足 Acceptance Criteria
- 是否违反架构设计
- 是否出现潜在 Bug
- 是否存在安全问题
- 是否引入不必要复杂度
- 是否影响现有模块
- 是否需要补充测试

输出：

```json
{
  "approved": false,
  "issues": [
    {
      "severity": "high",
      "file": "auth/service.py",
      "line": 72,
      "problem": "JWT expiration is not validated",
      "suggestion": "Validate exp before accepting token"
    }
  ]
}
```

---

# 21. Self-correction Loop

## Test Loop

```text
Coding
  ↓
Testing
  ↓
PASS?
 /   \
NO   YES
↓     ↓
Fix  Review
```

## Review Loop

```text
Reviewer
   ↓
Approved?
 /       \
NO       YES
↓         ↓
Fix      Finish
```

最大次数：

```text
MAX_CODE_RETRY
MAX_TEST_RETRY
MAX_REVIEW_RETRY
```

超过阈值后：

```text
Human Intervention
```

V2 起引入 Reflexion 自我反思层（见第 45 节），形成三层质量门：

```text
Self-Reflection → Test → Review
```

---

# 22. Git Workspace Isolation

并行 Agent 不共享同一工作目录。

采用：

```text
Repository
│
├── worktree/task-T1
│      └── branch/agent-T1
│
├── worktree/task-T2
│      └── branch/agent-T2
│
└── worktree/task-T3
       └── branch/agent-T3
```

每个 Coding Agent：

```text
Task
 ↓
Own Worktree
 ↓
Own Branch
 ↓
Patch
 ↓
Commit
```

---

# 23. Integration Agent

当多个并行开发任务完成后，由 Integration Agent 负责：

```text
Task A Commit ──┐
Task B Commit ──┼──→ Integration
Task C Commit ──┘
                     ↓
                Resolve Conflict
                     ↓
                  Full Test
```

Integration Agent 不负责重新实现业务逻辑。

主要职责：

- Merge
- Conflict Detection
- Conflict Resolution
- Integration Test

---

# 24. Code RAG

Coding Agent 不能依赖单纯全文读取。

建立 Code RAG。

数据来源：

```text
Source Code
README
Architecture Docs
API Docs
Git History
Issues
Pull Requests
Coding Standards
```

检索：

```text
Query
 │
 ├── BM25
 │
 └── Dense Retrieval
         │
         ▼
        RRF
         │
         ▼
      Reranker
         │
         ▼
Relevant Code Context
```

可增加 Symbol Search：

```text
class
function
method
import
call relationship
```

最终形成：

```text
Lexical Retrieval
+
Semantic Retrieval
+
Symbol Retrieval
```

V2 升级 Agentic RAG（检索策略自主决策），V3 引入 GraphRAG（AST 代码知识图谱，图 + 向量混合检索）。详见第 45 节。

---

# 25. Research Agent

当 Coding / Architect Agent 缺少外部知识时，不让其无限猜测。

流程：

```text
Coding Agent
    ↓
Knowledge Missing
    ↓
Supervisor
    ↓
Research Agent
    ↓
Official Docs / Web / GitHub
    ↓
Structured Research Result
    ↓
Coding Agent
```

Research Agent 优先使用：

```text
Official Documentation
Official GitHub
API Reference
```

---

# 26. Shared State

LangGraph State 不应该保存无限文本。

建议设计：

```python
class DevState(TypedDict):

    project_id: str
    user_request: str

    requirements: dict
    architecture: dict

    task_dag: list
    ready_tasks: list
    current_tasks: list
    completed_tasks: list

    changed_files: list
    commits: list

    test_results: dict
    review_results: dict

    current_agent: str

    iteration: int
    retry_count: int

    errors: list

    run_status: str
```

大型产物只保存引用：

```text
artifact_id
file_path
database_id
```

避免 Shared State 无限增长。

---

# 27. Memory Architecture

系统记忆分为三层。

## Working Memory

当前 Agent：

```text
Current Task
Recent Tool Calls
Recent Errors
Current Plan
```

## Project Memory

当前项目：

```text
Requirements
Architecture
Task Status
Coding Conventions
Important Decisions
```

## Long-term Memory

跨任务知识：

```text
Architecture Decision Records
Common Project Patterns
Frequently Seen Errors
Stable User Preferences
```

---

# 28. LangGraph 设计

整体采用：

```text
Main Graph
+
Development SubGraph
+
Coding SubGraph
```

---

# 29. Main Graph

```text
START
  ↓
Load Project
  ↓
Supervisor
  ↓
Product
  ↓
Architect
  ↓
Development SubGraph
  ↓
Final Review
  ↓
Human Approval
  ↓
END
```

注意：

实际执行不是完全固定路线。

Supervisor 可以通过 Conditional Edge 动态跳转。

---

# 30. Development SubGraph

```text
Task Scheduler
       ↓
Detect Ready Tasks
       ↓
Parallel Coding Agents
       ↓
Integration
       ↓
Testing
     /      \
  Failed    Passed
    ↓          ↓
 Repair      Review
               ↓
             Return
```

---

# 31. Coding SubGraph

```text
Receive Task
    ↓
Retrieve Context
    ↓
Explore Repository
    ↓
Generate Plan
    ↓
Edit Code
    ↓
Run Validation
    ↓
Success?
 /         \
NO         YES
↓           ↓
Repair     Finish
```

---

# 32. Checkpoint & Recovery

软件开发任务属于长任务。

LangGraph 每个关键节点后保存：

```text
State
+
Current Agent
+
Task Status
+
Tool Results
```

故障时：

```text
Load Last Checkpoint
        ↓
Resume
```

而不是从需求分析重新开始。

---

# 33. MCP Integration

第三方工具通过 MCP 统一连接。

例如：

```text
GitHub MCP
Jira MCP
Documentation MCP
Database MCP
Search MCP
```

结构：

```text
Agent
 ↓
Harness
 ↓
MCP Client
 ↓
MCP Server
 ↓
External Service
```

MCP 属于：

> **Tool connectivity layer**

Harness 属于：

> **Agent runtime layer**

二者职责不同。

MCP 与 A2A 分工（V2，见第 45 节）：

```text
MCP → 工具、数据与文档接入
A2A → Agent 与 Agent 之间的协作互操作
```

---

# 34. Observability

所有 Agent Run 必须可追踪。

Trace：

```text
Project Run
│
├── Supervisor
│
├── Architect
│
├── Coding Agent
│   ├── search_code
│   ├── read_file
│   ├── edit_file
│   └── run_test
│
├── Tester
└── Reviewer
```

记录：

```text
model
agent
tool
latency
token usage
cost
tool result
error
retry count
sandbox usage
```

---

# 35. Evaluation

系统不能只看 Demo 效果。

需要设计 Evaluation。

## Task Success

```text
任务是否完成
```

## Test Pass Rate

```text
最终测试通过率
```

## First-pass Success Rate

```text
第一次 Coding 后直接通过 Test/Review 的比例
```

## Retry Count

```text
平均修复次数
```

## Patch Correctness

```text
Patch 是否正确解决问题
```

## Regression Rate

```text
是否破坏已有功能
```

## Agent Routing Accuracy

```text
Supervisor 是否选择了正确 Agent
```

## Cost

```text
Tokens
API Cost
Tool Calls
Execution Time
```

## Regression Suite

```text
Golden Set
（固定评测任务集合）

Offline Regression
（离线回归评测）

与 DSPy 优化（V3）共享评测数据
```

---

# 36. Backend Architecture

推荐：

```text
FastAPI
```

API：

```text
POST /projects
POST /projects/{id}/runs

GET /runs/{id}
GET /runs/{id}/state

GET /runs/{id}/events

POST /runs/{id}/resume

GET /runs/{id}/tasks

GET /runs/{id}/diff

POST /runs/{id}/approve
```

---

# 37. Streaming

客户端（Tauri 2）通过 SSE 接收事件流：

```text
SSE
```

实时展示：

```text
Supervisor analyzing project...

Architect generated 6 tasks.

Task T1 ready.

Coding Agent started T1.

search_code("JWT")

read_file("src/auth.py")

edit_file("src/auth.py")

Running pytest...

2 tests failed.

Repairing...

52 tests passed.

Reviewer approved.
```

---

# 38. Desktop Client

技术方案：

```text
Tauri 2
+
React
```

选择理由：

- 桌面客户端形态（打包为 exe / msi），无浏览器依赖
- 复用成熟 UI 组件生态，视觉效果与开发效率兼得
- 与后端通过 REST + SSE 对接，无需改动 API

组件选型：

```text
React Flow    → Task DAG 拓扑可视化
Monaco Editor → Diff 查看器（语法高亮）
Tailwind CSS  → 现代深色主题
Recharts      → Token / 成本图表
```

界面布局：

```text
Project Header（项目 / 运行状态 / Cost）

左侧    Task DAG（拓扑图）
中间    Agent Trace（实时轨迹流）
右侧    Diff Viewer（代码变更）

底部    Approval Panel（人工审批）
```

交付节奏：MVP 阶段以 CLI / API 验证流程，客户端随 V2 的 SSE Streaming 一同交付。

核心模块：

## Project Dashboard

显示：

- Project
- Repository
- Current Run
- Current Agent
- Task DAG
- Agent Timeline
- Cost

## Task DAG

React Flow 渲染拓扑，节点实时变色：

```text
T1 ●──→ T2 ●
 \
  └──→ T3 ○
```

颜色状态：

```text
Pending
Running
Completed
Failed
Blocked
```

## Agent Trace

显示：

```text
Coding Agent

1. search_code
2. read_file
3. edit_file
4. run_test
5. repair
```

## Diff Viewer

Monaco Editor 展示最终 Patch 与逐文件 Diff。

## Approval Panel

人工批准：

```text
Commit
Push
Merge
Deploy
```

---

# 39. Storage

## PostgreSQL

保存：

```text
users
projects
runs
tasks
agent_runs
tool_runs
checkpoints
reviews
approvals
```

## Redis

保存：

```text
temporary state
cache
event stream
task coordination
```

## Vector DB

保存：

```text
code embedding
documentation embedding
project memory
```

推荐：

```text
pgvector / Qdrant / OpenSearch
```

---

# 40. 推荐技术栈

```text
Desktop Client
Tauri 2 + React

Backend
FastAPI

Agent Orchestration
LangGraph

Agent Runtime
Custom Unified Harness

Agent Interop
MCP + A2A

Agent Skills
Dynamic Skill Packages

LLM
OpenAI / Claude / Gemini / Local Models

Structured Output
Pydantic

Prompt Optimization
DSPy

Code Retrieval
BM25
Dense Retrieval
RRF
Reranker
Symbol Search

Code Graph
GraphRAG

Database
PostgreSQL

Vector Database
pgvector / Qdrant / OpenSearch

Cache
Redis

Sandbox
Docker

Version Control
Git / Git Worktree

External Integration
MCP

Safety
Guardrails + Reflexion

Observability
LangSmith
OpenTelemetry
Prometheus
Grafana
```

---

# 41. 推荐代码目录

```text
app/
│
├── api/
│
│   ├── projects.py
│   ├── runs.py
│   └── approvals.py
│
├── graph/
│   ├── main_graph.py
│   ├── development_graph.py
│   ├── coding_graph.py
│   ├── state.py
│   └── routing.py
│
├── agents/
│   ├── supervisor.py
│   ├── product.py
│   ├── architect.py
│   ├── coder.py
│   ├── tester.py
│   ├── reviewer.py
│   └── researcher.py
│
├── harness/
│   ├── runtime.py
│   ├── context.py
│   ├── registry.py
│   ├── executor.py
│   ├── observation.py
│   ├── policy.py
│   ├── permission.py
│   ├── approval.py
│   ├── sandbox.py
│   ├── retry.py
│   └── tracing.py
│
├── tools/
│   ├── filesystem/
│   ├── git/
│   ├── shell/
│   ├── testing/
│   └── mcp/
│
├── retrieval/
│   ├── bm25.py
│   ├── vector.py
│   ├── fusion.py
│   ├── reranker.py
│   └── symbol_search.py
│
├── workspace/
│   ├── manager.py
│   └── worktree.py
│
├── sandbox/
│   └── docker.py
│
├── memory/
│   ├── working.py
│   ├── project.py
│   └── long_term.py
│
├── schemas/
│
├── storage/
│
└── observability/
```

客户端（monorepo 子目录）：

```text
client/
├── src/          （React 界面）
├── src-tauri/    （Tauri 2 外壳）
└── package.json
```

---

# 42. MVP

第一阶段只做：

```text
User
 ↓
Product Agent
 ↓
Architect Agent
 ↓
Coding Agent
 ↓
Test Agent
 ↓
Reviewer Agent
 ↓
Git Diff
 ↓
Human Approval
```

> 说明：MVP 阶段由 Supervisor 以固定顺序调度；V2 起升级为基于 Shared State 的动态路由。

同时完成基础 Harness：

```text
ContextManager
ToolRegistry
ToolExecutor
PermissionManager
Docker Sandbox
TraceManager
```

工具：

```text
read_file
search_code
edit_file
git_diff
run_test
```

MVP 不做：

```text
Parallel Agent
MCP
Long-term Memory
Complex RAG
Automatic Git Push
Deployment
```

---

# 43. V2

增加：

```text
Supervisor Dynamic Routing

Code RAG（含 Agentic RAG）

Task DAG

Parallel Coding Agents

Git Worktree

Checkpoint

Research Agent

MCP + A2A

Agent Skills

Context Engineering

Reflexion

Guardrails

HITL

SSE Streaming

Desktop Client（Tauri 2 + React）
```

---

# 44. V3

增加：

```text
Frontend Agent
Backend Agent
Database Agent
Security Agent
DevOps Agent
Integration Agent

Multi-repository Support

PR Automation

Long-term Project Memory

Automatic Evaluation

Agent Cost Optimization

DSPy（指令链路程序化优化）

GraphRAG（代码知识图谱）
```

---

# 45. 智能层增强技术（V2 / V3）

本节描述在 Unified Harness 与多 Agent 体系之上引入的智能层增强技术。

目标：

```text
互操作性（A2A）
+
技能化（Agent Skills）
+
检索质量（Agentic RAG / GraphRAG）
+
上下文效率（Context Engineering）
+
自纠错（Reflexion）
+
安全性（Guardrails）
```

---

## 45.1 A2A Protocol（Agent 互操作）

MCP 解决 “Agent 如何使用工具”，A2A（Agent2Agent）解决 “Agent 之间如何协作”。

```text
External Agent Platform
          │
          ▼
    ┌───────────┐   A2A   ┌────────────┐
    │ External  │◄───────►│   本系统    │
    │ Agent     │         │ Supervisor │
    └───────────┘         └────────────┘
```

落地方式：

- 以 Agent Card 形式对外暴露本系统能力
- 支持接收外部 Agent 的 Task 请求并返回结构化结果
- 内部仍使用 Shared State + 结构化协议，边界适配由 Harness 承载

```text
MCP（工具层）
+
A2A（协作层）
=
双协议栈
```

---

## 45.2 Agent Skills（动态技能体系）

将 Agent 能力从 “写死在 Prompt 中” 升级为 “按需动态加载的技能包”。

```text
skills/
├── jwt-auth/
│   └── SKILL.md
├── react-form/
│   └── SKILL.md
└── postgres-migration/
    └── SKILL.md
```

- Coding Agent 按任务类型动态加载对应 Skill（由 ContextManager 装配）
- Skill 内含领域知识、规范、示例与检查清单
- 避免一次性注入所有知识与规范，降低上下文压力

---

## 45.3 DSPy（程序化优化 Agent Pipeline）

将 Product / Architect / Reviewer 等节点的 Prompt 从 “手写调参” 升级为 “程序化自动优化”。

```text
Agent 模块（声明式定义）
        ↓
DSPy Optimizer
        ↓
评测集（Golden Set）
        ↓
自动编译出最优 Prompt
```

- 依赖评测集与运行数据，安排在 V3
- 与 Observability / Evaluation 打通：真实运行轨迹与评测数据作为优化来源

---

## 45.4 GraphRAG / Agentic RAG（代码知识图谱检索）

在 Code RAG（BM25 + Dense Retrieval + RRF + Reranker + Symbol Search）之上增加结构化代码理解。

Agentic RAG（V2）：

```text
Query
  ↓
检索策略 Agent
（向量 / BM25 / 符号 / 图检索 / 多跳）
  ↓
结果自检（是否充分？）
  ↓ 不足
更换策略重新检索
  ↓ 充分
返回上下文
```

GraphRAG（V3）：

```text
Source Code
    ↓
AST / 符号解析（tree-sitter）
    ↓
代码知识图谱
（类 / 函数 / 调用关系 / 模块依赖）
    ↓
图检索 + 向量检索混合
    ↓
Coding Agent
```

---

## 45.5 Context Engineering（上下文工程）

长任务上下文必然溢出，由 ContextManager 工程化治理。

Compaction（压缩）：

```text
历史消息 / 工具原始输出
        ↓
超过阈值触发
        ↓
摘要压缩（保留决策、结论、文件路径）
        ↓
继续执行
```

Sub-Agent 上下文隔离：

```text
Supervisor（全局状态）
    │
    ├── Sub-Agent A（独立上下文）
    └── Sub-Agent B（独立上下文）
```

- 子 Agent 仅接收必要的任务切片上下文
- 工具原始输出（如全量日志）经 Observation Adapter 压缩后再进入主上下文
- 主 State 只保留结构化结论

---

## 45.6 Reflexion（自我反思机制）

在修复循环中增加 “自我批判” 层，减少无效修复与反复重测。

```text
Test Failed
    ↓
Coding Agent 修复
    ↓
Self-Reflection
（是否真正解决根因？影响面是否完整？）
    ↓ 不通过
重新分析
    ↓ 通过
提交重测
```

与现有闭环叠加，形成三层质量门：

```text
Self-Reflection → Test → Review
```

---

## 45.7 Guardrails（Agent 安全护栏）

由 Harness 中的 GuardrailManager 承载。

```text
用户输入 / 代码内容 / 工具输出
        ↓
输入护栏
（Prompt Injection 检测、越权请求检测）
        ↓
Agent 执行
        ↓
输出护栏
（结构校验、敏感信息检测）
        ↓
放行 / 拦截
```

- 输入侧：Prompt Injection、恶意指令、越权请求
- 输出侧：JSON Schema 校验、敏感信息泄漏检测
- 与 Policy Engine / Human-in-the-loop 联动：护栏拦截升级人工审批

---

## 45.8 版本融入点

| 技术 | 版本 | 依赖 |
|------|------|------|
| Agentic RAG | V2 | 现有 Code RAG |
| Context Engineering | V2（MVP 基线） | ContextManager |
| Reflexion | V2 | 现有 Self-correction Loop |
| Guardrails | V2 | Policy Engine |
| A2A Protocol | V2 | MCP 集成经验 |
| Agent Skills | V2 | — |
| DSPy | V3 | 评测集 + 运行数据 |
| GraphRAG | V3 | Code RAG + AST 解析 |

---

# 46. 关键创新点

本项目重点不是“Agent 数量”。

真正技术亮点包括：

### 1. LangGraph Dynamic Orchestration

使用：

```text
StateGraph
Conditional Edge
Command
SubGraph
Checkpoint
Interrupt
```

构建动态 Agent Workflow。

### 2. Unified Agent Harness

建立统一 Agent Runtime，实现：

```text
Context
Tools
Policy
Permissions
Sandbox
Observation
Retry
Tracing
```

### 3. Capability-based Permission

通过 Capability Profile 控制不同 Agent 权限。

### 4. Task DAG

支持：

```text
dependency
parallelism
blocking
retry
```

### 5. Code RAG

结合：

```text
BM25
Dense Retrieval
RRF
Reranker
Symbol Search
```

提供代码上下文。

### 6. Self-correcting Development

形成：

```text
Code
 ↓
Test
 ↓
Review
 ↓
Fix
```

闭环。

### 7. Workspace Isolation

采用：

```text
Git Branch
+
Git Worktree
+
Docker Sandbox
```

支持并行、安全执行。

### 8. Human Governance

高风险操作必须通过：

```text
Policy
+
Approval
+
Interrupt
```

### 9. A2A + MCP 双协议栈

MCP 负责工具接入，A2A 负责 Agent 互操作，形成对外协作生态。

### 10. Agent Skills

能力以技能包形式动态加载，替代全量 Prompt 注入。

### 11. GraphRAG 代码知识图谱

AST 解析构建代码知识图谱，实现图 + 向量混合检索。

### 12. DSPy 程序化优化

以评测集驱动，自动编译优化 Agent 指令链路。

### 13. Reflexion + Guardrails

自我反思质量门与输入输出安全护栏，构建可信 Agent 执行链路。

---

# 47. 项目与 MetaGPT 的区别

MetaGPT 更偏：

```text
Role
+
SOP
+
Software Team Simulation
```

本项目重点为：

```text
Dynamic Orchestration
+
Agent Runtime
+
Real Repository Operation
+
Sandbox
+
Code Retrieval
+
Self Repair
+
State Persistence
```

因此不是简单：

```text
PM → Architect → Engineer → Tester
```

而是：

```text
Current State
      ↓
Supervisor
      ↓
Choose Agent
      ↓
Agent + Harness
      ↓
Environment
      ↓
Observation
      ↓
State Update
      ↓
Next Decision
```

---

# 48. 项目最终定位

项目最终定位为：

> **面向真实代码仓库的 Multi-Agent Software Engineering Platform。**

核心技术组合：

```text
LangGraph
+
Multi-Agent
+
Agent Harness
+
Code RAG（Agentic RAG / GraphRAG）
+
Agent Skills
+
Task DAG
+
Tool Calling
+
MCP + A2A
+
Git Worktree
+
Docker Sandbox
+
Context Engineering
+
Reflexion
+
Guardrails
+
Checkpoint
+
Human-in-the-loop
```

系统最终目标不是实现一个“会生成代码的聊天机器人”，而是实现一个：

> **具备任务规划、代码理解、工具执行、测试反馈、自我修复、状态恢复、安全隔离与人工治理能力的软件开发 Agent Runtime。**

---

# 49. 简历描述

可在简历中描述为：

> 设计并实现基于 LangGraph 的多 Agent 软件开发系统，通过 Supervisor 对 Product、Architect、Coding、Testing、Review 等专业 Agent 进行动态编排；基于 Shared State、Structured Output 与 Task DAG 实现 Agent 间任务依赖管理和并行协作，并构建 Code-Test-Review-Fix 自动修复闭环。

> 设计统一 Agent Harness Runtime，封装 Context Management、Tool Registry、Permission Policy、Observation Adapter、Retry、Tracing 与 Docker Sandbox，并基于 Capability Profile 为不同 Agent 提供最小权限执行环境；结合 Git Worktree 实现并行 Agent Workspace 隔离。

> 构建面向代码仓库的 Hybrid Code RAG，通过 BM25、Dense Retrieval、RRF、Reranker 与 Symbol Search 为 Coding Agent 动态提供相关代码上下文，同时结合 LangGraph Checkpoint、Human-in-the-loop 与 MCP，实现长任务恢复、高风险操作审批和外部工具扩展。

> 引入 A2A 协议与 MCP 组成双协议栈，实现与外部 Agent 体系互操作；采用 Agent Skills 构建动态技能体系，基于 DSPy 对 Agent 指令链路进行程序化优化；通过 GraphRAG 代码知识图谱与 Agentic RAG 提升代码检索质量；结合 Context Engineering（上下文压缩与子 Agent 隔离）、Reflexion 自我反思与 Guardrails 安全护栏，构建高效、可自纠错、安全可控的 Agent 执行链路。