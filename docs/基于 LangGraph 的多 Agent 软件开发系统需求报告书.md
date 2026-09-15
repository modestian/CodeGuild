# 基于 LangGraph 的多 Agent 软件开发系统需求报告书

| 项目 | 内容 |
|------|------|
| 文档名称 | 基于 LangGraph 的多 Agent 软件开发系统需求报告书 |
| 文档版本 | V1.0 |
| 文档状态 | 评审稿 |
| 编制日期 | 2026-09-13 |
| 编制依据 | 《基于 LangGraph 的多 Agent 软件开发系统设计方案》（唯一依据） |
| 适用范围 | 需求评审、系统设计、编码实现、测试与验收 |

> 说明：本文档全部需求均可追溯到设计方案对应章节，详见第 11 章需求追踪矩阵。

---

## 1. 引言

### 1.1 编写目的

本文档以《基于 LangGraph 的多 Agent 软件开发系统设计方案》为唯一依据，将设计方案中的项目目标、架构设计、Agent 角色、Harness 运行时、安全治理机制、智能层增强技术与版本规划转化为可评审、可开发、可验收的需求基线。

预期读者：需求评审人员、系统开发者、测试人员与项目管理人员。

### 1.2 项目背景

现有 AI 编码工具以"单 Agent + 文本生成"为主，缺乏真实软件团队中的角色分工、任务依赖管理、真实代码仓库操作、安全执行环境与质量反馈闭环，难以支撑完整的软件工程流程。

本项目构建一个围绕真实代码仓库持续执行软件开发任务的多 Agent 系统（Multi-Agent Software Development Copilot），以共享状态、任务依赖、动态调度、工具执行和反馈闭环为核心，实现从自然语言需求到 Git Diff / 人工审批 / 提交的完整流程。

### 1.3 术语与缩略语

| 术语/缩略语 | 说明 |
|-------------|------|
| Agent | 具有明确软件工程职责的智能体（Product、Architect、Coding、Test、Review 等） |
| Supervisor | 中央协调 Agent，负责状态判断与下一 Agent 选择 |
| Orchestration | 编排层（LangGraph），决定"哪个 Agent 工作" |
| Harness | 统一运行时（AgentRuntime），负责"如何安全、稳定地执行" |
| Capability Profile | Agent 能力画像，定义工具集、权限、shell 限制与 max_steps |
| Policy Engine | 策略引擎，工具执行前的校验链与风险决策 |
| Observation Adapter | 观测适配器，对工具原始输出进行截断、摘要与压缩 |
| Shared State | LangGraph 共享状态，Agent 协作的统一数据载体 |
| Artifact | 结构化软件工程产物（需求/架构/任务/补丁/报告） |
| Task DAG | 任务有向无环图，支持依赖与并行 |
| Task Scheduler | 任务调度器，依据依赖判定就绪任务（READY TASKS） |
| Code RAG | 代码检索增强，BM25 + Dense Retrieval + RRF + Reranker + Symbol Search |
| Agentic RAG | 检索策略由 Agent 自主决策并自检的 RAG（V2） |
| GraphRAG | 基于 AST 代码知识图谱的图 + 向量混合检索（V3） |
| Symbol Search | 符号检索（class/function/method/import/call relationship） |
| RRF | Reciprocal Rank Fusion，多路检索融合算法 |
| MCP | Model Context Protocol，工具接入层 |
| A2A | Agent2Agent 协议，Agent 间互操作层（V2） |
| Agent Skills | 动态技能包体系（V2） |
| DSPy | 程序化优化 Agent 指令链路的框架（V3） |
| Context Engineering | 上下文工程：压缩、隔离、动态装配（V2） |
| Reflexion | 自我反思机制（V2） |
| Guardrails | Agent 输入输出安全护栏（V2） |
| HITL | Human-in-the-loop，人工审批 |
| SSE | Server-Sent Events，服务端事件流 |
| Checkpoint | 检查点，长任务状态保存与恢复 |
| Worktree | Git 工作树，并行 Agent 工作区隔离 |
| Golden Set | 固定评测任务集合，用于离线回归评测 |

### 1.4 需求编号与优先级说明

需求编号规则：

| 前缀 | 含义 |
|------|------|
| FR-XXX-nn | 功能需求（Functional Requirement） |
| NFR-XXX-nn | 非功能需求（Non-Functional Requirement） |
| IR-nn | 接口需求（Interface Requirement） |
| DR-nn | 数据需求（Data Requirement） |

优先级定义（与设计方案的 MVP / V2 / V3 分期对应）：

| 优先级 | 含义 | 对应版本 |
|--------|------|----------|
| 必须 | 核心必要需求，缺失则系统无法达成基本目标 | MVP |
| 应当 | 重要增强需求 | V2 |
| 可选 | 远期扩展需求 | V3 |

---

## 2. 项目总体描述

### 2.1 项目定位

项目定位为：

> **面向真实代码仓库的 Multi-Agent Software Engineering Platform。**

它不是"会生成代码的聊天机器人"，而是具备任务规划、代码理解、工具执行、测试反馈、自我修复、状态恢复、安全隔离与人工治理能力的软件开发 Agent Runtime。

### 2.2 项目目标

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

核心目标不是让多个 LLM 按固定顺序生成文本，而是构建基于共享状态、任务依赖、动态调度、工具执行和反馈闭环的 Agent 软件工程系统。

### 2.3 系统用户与角色

| 角色 | 职责 |
|------|------|
| 最终用户 | 提交开发需求、查看运行进度与成本、对高风险操作进行人工审批 |
| 开发者 | 维护 Agent 角色、工具、Capability Profile、Policy 与系统配置 |
| 管理员 | 管理项目、运行环境、凭证与沙箱资源 |

### 2.4 系统范围

包含：

- LangGraph 多 Agent 编排（Main Graph / Development SubGraph / Coding SubGraph）
- 专业 Agent 协作（Supervisor、Product、Architect、Coding、Test、Reviewer、Research）
- 统一 Agent Harness（上下文、工具、权限、策略、审批、沙箱、观测、重试、状态、追踪）
- Task DAG 与任务调度
- Code RAG 检索体系
- 自纠错闭环（Code → Test → Review → Fix）
- Git 工作区隔离、Docker 沙箱、人工审批
- Checkpoint 与故障恢复
- 后端 API、SSE 事件流、桌面客户端
- 可观测性与评测体系
- 智能层增强技术（V2/V3）

不包含（MVP 明确不做 / 远期规划）：

- MVP 不做：并行 Agent、MCP、长期记忆、复杂 RAG、自动 Git Push、部署
- 远期（V3）：多仓库支持、PR 自动化、自动评测、Agent 成本优化等

### 2.5 总体业务流程

```text
User Request
     ↓
Product Agent（需求结构化）
     ↓
Architect Agent（技术设计 + Task DAG）
     ↓
Task Scheduler（就绪任务）
     ↓
Coding Agent（可并行）
     ↓
Integration Agent（合并）
     ↓
Test Agent（测试验证）
     ↓ 失败循环（受重试上限约束）
     ↓ 通过
Reviewer Agent（代码审查）
     ↓ 不通过循环（受重试上限约束）
     ↓ 通过
Git Diff 生成
     ↓
Human Approval（人工审批）
     ↓
Git Commit / PR
```

### 2.6 核心设计原则

| 编号 | 原则 | 说明 |
|------|------|------|
| P1 | Orchestration 与 Execution 分离 | LangGraph 决定"哪个 Agent 工作"；Agent 决定"当前应该做什么"；Harness 负责"如何安全、稳定地执行" |
| P2 | Agent 专业化 | 每个 Agent 只负责明确的软件工程职责，不设计万能 Agent |
| P3 | State-driven Collaboration | Agent 之间不依赖自由聊天，通过 Structured Output + Shared State 协作 |
| P4 | Artifact-driven Collaboration | Agent 之间传递结构化产物：Requirements → Architecture → Task DAG → Code Patch → Test Report → Review Report |
| P5 | 闭环优先 | 必须形成 Code → Test → Review → Fix → Test 闭环，而非生成即结束 |
| P6 | Least Privilege | 不同 Agent 拥有不同工具与权限（如 Reviewer 只读） |
| P7 | Safe Execution | 所有用户代码 / Agent 生成代码的执行均在 Sandbox 中运行 |

### 2.7 分层架构

| 层次 | 组成 | 职责 |
|------|------|------|
| API Layer | FastAPI / SSE | 对外接口与事件流 |
| Orchestration Layer | LangGraph / Shared State / Supervisor / Task DAG / Task Scheduler | 多 Agent 编排、状态流转、条件路由 |
| Agent Layer | Role / Goal / Prompt | 各专业 Agent 的推理、规划与动作选择 |
| Harness Layer | Unified Agent Runtime（Context / Tool / Policy / Permission / Approval / Guardrail / Sandbox / Observation / Retry / State / Trace） | 安全、稳定的执行环境 |
| Infrastructure Layer | PostgreSQL / Redis / Vector DB / Git / Docker / LangSmith / OpenTelemetry / Metrics | 存储、执行与观测基础设施 |

### 2.8 运行环境与技术栈

| 层次 | 技术选型 |
|------|----------|
| 桌面客户端 | Tauri 2 + React |
| 后端 | FastAPI |
| Agent 编排 | LangGraph |
| Agent 运行时 | Custom Unified Harness |
| Agent 互操作 | MCP + A2A |
| Agent 技能 | Agent Skills（Dynamic Skill Packages） |
| LLM | OpenAI / Claude / Gemini / Local Models |
| 结构化输出 | Pydantic |
| Prompt 优化 | DSPy |
| 代码检索 | BM25 / Dense Retrieval / RRF / Reranker / Symbol Search |
| 代码图谱 | GraphRAG |
| 数据库 | PostgreSQL |
| 向量库 | pgvector / Qdrant / OpenSearch |
| 缓存 | Redis |
| 沙箱 | Docker |
| 版本控制 | Git / Git Worktree |
| 外部集成 | MCP |
| 安全 | Guardrails + Reflexion |
| 可观测性 | LangSmith / OpenTelemetry / Prometheus / Grafana |

---

## 3. 功能需求

### 3.1 系统编排与调度（Supervisor）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-SUP-01 | 项目状态判断 | 判断当前项目状态与当前任务所处阶段 | 必须 |
| FR-SUP-02 | 结果处理 | 处理各 Agent 的执行结果并更新调度依据 | 必须 |
| FR-SUP-03 | 阻塞识别 | 识别任务阻塞并做出调度决策 | 必须 |
| FR-SUP-04 | 重试控制 | 控制各闭环的重试次数 | 必须 |
| FR-SUP-05 | 重新规划判断 | 判断是否需要触发重新规划 | 应当 |
| FR-SUP-06 | 人工介入判断 | 判断是否需要人工介入 | 必须 |
| FR-SUP-07 | 任务结束判断 | 判断任务是否结束 | 必须 |
| FR-SUP-08 | 动态路由 | 基于 Shared State 通过 Conditional Edge 动态选择下一执行 Agent（V2 起） | 应当 |
| FR-SUP-09 | 调度轻量原则 | Supervisor 不直接写代码、不执行具体开发任务 | 必须 |

验收要点：

- 调度决策输出必须包含 next_agent 与 reason
- 测试失败场景（tests_passed=false）必须正确路由至 Coding Agent
- MVP 阶段以固定顺序调度，V2 起升级为动态路由

### 3.2 需求分析（Product Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-PROD-01 | 需求结构化 | 将自然语言需求转化为结构化产品需求 | 必须 |
| FR-PROD-02 | Feature 拆分 | 拆分 features 列表 | 必须 |
| FR-PROD-03 | 用户故事 | 拆分 user_stories | 必须 |
| FR-PROD-04 | 验收标准 | 生成 acceptance_criteria | 必须 |
| FR-PROD-05 | 非功能需求 | 提取 non_functional_requirements | 必须 |
| FR-PROD-06 | 冲突与缺失发现 | 发现需求冲突与缺失，输出 open_questions 请求澄清 | 必须 |

验收要点：

- 输出必须为结构化 JSON，字段包含 features / user_stories / acceptance_criteria / non_functional_requirements / open_questions
- 输入为：用户需求、现有项目背景、项目约束

### 3.3 架构设计（Architect Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-ARCH-01 | 技术方案 | 将产品需求转化为技术方案 | 必须 |
| FR-ARCH-02 | 模块划分 | 划分系统模块边界 | 必须 |
| FR-ARCH-03 | API 契约 | 定义 API 契约 | 必须 |
| FR-ARCH-04 | 数据模型 | 设计数据模型 | 必须 |
| FR-ARCH-05 | 模块依赖 | 分析模块依赖关系 | 必须 |
| FR-ARCH-06 | Task DAG 输出 | 输出任务列表（含 id / title / depends_on），依赖关系无环 | 必须 |

### 3.4 任务管理（Task DAG）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-TASK-01 | 任务结构 | 任务包含 id、title、dependencies、status、assigned_agent、priority 字段 | 必须 |
| FR-TASK-02 | 状态机 | 状态支持 PENDING / READY / RUNNING / BLOCKED / REVIEWING / COMPLETED / FAILED | 必须 |
| FR-TASK-03 | DAG 表达 | 任务使用 DAG 表达依赖关系，而非简单列表 | 应当 |
| FR-TASK-04 | 就绪判定 | Task Scheduler 根据依赖关系确定 READY TASKS | 应当 |
| FR-TASK-05 | 并行执行 | 无依赖关系的任务支持并行执行 | 应当 |
| FR-TASK-06 | 阻塞处理 | 依赖失败时相关任务进入 BLOCKED 状态 | 应当 |

### 3.5 代码生成与修改（Coding Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-CODE-01 | 仓库探索 | 在修改前进行 Repository Exploration | 必须 |
| FR-CODE-02 | 代码检索 | 通过 Code Retrieval 获取相关代码，禁止依赖全文读取 | 必须 |
| FR-CODE-03 | 文件阅读 | 阅读相关文件理解上下文 | 必须 |
| FR-CODE-04 | 修改计划 | 制定 Plan 后再执行修改 | 必须 |
| FR-CODE-05 | 代码修改 | 执行 Edit 完成真实代码修改 | 必须 |
| FR-CODE-06 | 运行验证 | 修改后执行 Run Validation | 必须 |
| FR-CODE-07 | 结果检查与迭代 | Inspect Result 后执行 Fix 或 Finish | 必须 |
| FR-CODE-08 | 标准工作流 | 遵循 Task → Repository Exploration → Code Retrieval → Read → Plan → Edit → Run Validation → Inspect → Fix / Finish 流程 | 必须 |
| FR-CODE-09 | LLM + Harness 边界 | Agent 决定"下一步做什么"，Harness 决定"实际如何执行" | 必须 |

验收要点：

- 修改结果必须可生成 Git Diff
- 所有验证执行必须发生在沙箱内

### 3.6 统一 Agent Harness（运行时）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-HARNESS-01 | 统一运行时 | 建立统一 AgentRuntime，所有 Agent 共用同一 Harness，不为每个 Agent 重复实现 | 必须 |
| FR-HARNESS-02 | 组件体系 | AgentRuntime 包含 ContextManager、ToolRegistry、ToolExecutor、PolicyEngine、PermissionManager、ApprovalManager、SandboxManager、ObservationAdapter、RetryManager、StateManager、TraceManager | 必须 |
| FR-HARNESS-03 | 护栏管理 | AgentRuntime 包含 GuardrailManager（V2，见第 45 节） | 应当 |
| FR-HARNESS-04 | 三层职责分离 | LangGraph 编排 / Agent 决策 / Harness 执行三层职责严格分离 | 必须 |
| FR-HARNESS-05 | 状态与追踪 | StateManager 管理共享状态读写，TraceManager 记录调用链路 | 必须 |
| FR-HARNESS-06 | 重试管理 | RetryManager 统一处理工具与模型调用的失败重试 | 应当 |

验收要点：

- 所有 Agent 必须通过同一 AgentRuntime 执行，禁止绕过 Harness 直接调用工具
- 新增 Agent 不需要重新实现 Harness 组件

### 3.7 上下文管理（Context Manager）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-CTX-01 | 最小必要上下文 | 为每次模型调用构造最必要上下文：System Prompt + Current Task + Acceptance Criteria + Architecture Constraints + Relevant Code Chunks + Recent Tool Results + Current Errors | 必须 |
| FR-CTX-02 | 禁止全库注入 | 不把整个代码库放入 Prompt | 必须 |
| FR-CTX-03 | 上下文压缩 | Compaction：超阈值时对历史消息与工具输出摘要压缩，保留决策、结论、文件路径（V2） | 应当 |
| FR-CTX-04 | 子 Agent 隔离 | Sub-Agent Context Isolation：子 Agent 使用独立上下文，仅接收任务切片（V2） | 应当 |
| FR-CTX-05 | 动态装配 | Dynamic Assembly：按任务类型动态拼装上下文（V2，含 Agent Skills 装配） | 应当 |

### 3.8 工具系统（Tool Registry / Tool Definition）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-TOOL-01 | 工具注册 | ToolRegistry 统一注册系统可用工具，分为 Filesystem / Git / Execution / Retrieval / External 五类 | 必须 |
| FR-TOOL-02 | 工具定义规范 | 每个 Tool 至少包含 name、description、input_schema、output_schema、risk_level、timeout、required_permission | 必须 |
| FR-TOOL-03 | Filesystem 工具集 | 提供 list_files、read_file、search_code、grep、read_symbol、edit_file、create_file、apply_patch | 必须 |
| FR-TOOL-04 | Git 工具集 | 提供 git_status、git_diff、git_log、git_branch、git_commit | 必须 |
| FR-TOOL-05 | Execution 工具集 | 提供 run_command、run_test、run_linter、run_build | 必须 |
| FR-TOOL-06 | Retrieval 工具集 | 提供 retrieve_code、search_docs、search_history | 应当 |
| FR-TOOL-07 | External 工具集 | 提供 github、jira、web_search、documentation，外部能力优先通过 MCP 接入 | 应当 |

### 3.9 权限体系（Capability Profile）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-CAP-01 | 统一 Runtime + 差异化配置 | 所有 Agent 共用 Harness，但拥有不同 Capability Profile | 必须 |
| FR-CAP-02 | Coding Agent 画像 | tools（read_file/search_code/edit_file/apply_patch/run_test/git_diff）、workspace: read_write、shell: sandbox_only、max_steps: 50 | 必须 |
| FR-CAP-03 | Test Agent 画像 | tools（read_file/run_test/run_linter/run_build）、workspace: read_only、source_edit: deny、max_steps: 20 | 必须 |
| FR-CAP-04 | Reviewer Agent 画像 | tools（read_file/search_code/git_diff/run_test）、workspace: read_only、edit_file: deny、max_steps: 15 | 必须 |
| FR-CAP-05 | 最小权限执行 | 按最小权限原则为不同 Agent 提供差异化执行环境 | 必须 |

验收要点：

- Reviewer 调用 edit_file 必须被拒绝
- Test / Reviewer 对工作区默认只读

### 3.10 策略引擎（Policy Engine）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-POL-01 | 校验链 | 工具真正执行前依次经过：Tool Call → Schema Validation → Policy Validation → Permission Check → Risk Evaluation → Execute / Approval / Reject | 必须 |
| FR-POL-02 | 风险分级 | 工具按 LOW / MEDIUM / HIGH / CRITICAL 四级风险分类 | 必须 |
| FR-POL-03 | 风险映射 | 建立动作风险映射（如 read_file=LOW、edit_file=MEDIUM、delete_file=HIGH、git_push=CRITICAL、database migration=CRITICAL） | 必须 |
| FR-POL-04 | 决策输出 | 每次工具调用必须输出明确决策：Execute / Approval / Reject | 必须 |
| FR-POL-05 | 与 Guardrails 分工 | Policy Engine 负责权限、风险与审批决策；Guardrails 负责语义级安全检测（V2） | 应当 |

### 3.11 人工审批（Human-in-the-loop）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-HITL-01 | 中断机制 | 高风险操作通过 LangGraph interrupt() 中断并等待人工审批 | 必须 |
| FR-HITL-02 | 自动允许 | read_file、search_code、git_diff、run_test、run_linter 自动允许 | 必须 |
| FR-HITL-03 | 可配置审批 | edit_file、delete_file、git_commit 建议可配置审批 | 必须 |
| FR-HITL-04 | 强制审批 | git_push、merge、deploy、database migration、production operation 强制人工审批 | 必须 |
| FR-HITL-05 | 审批流 | 审批通过（YES）→ 执行；拒绝（NO）→ Reject；审批后可从中断点恢复 | 必须 |
| FR-HITL-06 | 审批留痕 | 审批记录持久化（approvals 表），可查询与审计 | 应当 |

### 3.12 沙箱执行（Sandbox）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-SB-01 | 隔离执行 | 所有代码执行必须运行在隔离环境：Agent → Harness → Sandbox Manager → Docker Container → Command / Test / Build | 必须 |
| FR-SB-02 | 资源限制 | 沙箱提供 CPU 限制、内存限制与执行超时 | 必须 |
| FR-SB-03 | 环境隔离 | 文件系统隔离、网络权限控制、Environment Variables 管理 | 必须 |
| FR-SB-04 | Secret 隔离 | 沙箱内进行 Secret Isolation，凭证不暴露给执行代码 | 必须 |
| FR-SB-05 | 禁访清单 | 默认禁止访问：Host filesystem、Host SSH Key、Production DB、Cloud Credentials、Private Environment Variables | 必须 |

### 3.13 观测适配（Observation Adapter）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-OBSA-01 | 结果不直接入上下文 | Tool 原始结果不直接全部交给模型（如 8000 行 pytest 输出必须转换） | 必须 |
| FR-OBSA-02 | 日志截断与错误摘要 | 对日志进行截断并生成错误摘要 | 必须 |
| FR-OBSA-03 | 结构化输出 | 将工具结果转为结构化数据（如 status / passed / failed / errors） | 必须 |
| FR-OBSA-04 | 敏感信息过滤 | 过滤输出中的敏感信息 | 必须 |
| FR-OBSA-05 | 重复消除与 Token 压缩 | 消除重复信息并进行 Token 压缩 | 必须 |

### 3.14 Agent 执行循环（Execution Loop）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-EXEC-01 | 标准循环 | 单 Agent 循环：Build Context → Model Call → Decision →（Final 或 Tool Call → Policy Check → Tool Executor → Observation → Update State → Model Call） | 必须 |
| FR-EXEC-02 | 停止条件 | 必须设置 max_steps、max_tokens、max_cost、timeout、max_tool_failures | 必须 |
| FR-EXEC-03 | 防无限循环 | 达到任一停止条件时必须安全终止循环 | 必须 |
| FR-EXEC-04 | 决策分支 | Decision 为 Final 时结束循环并返回结果 | 必须 |

### 3.15 自动化测试（Test Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-TEST-01 | 独立性 | Test Agent 独立于 Coding Agent | 必须 |
| FR-TEST-02 | 单元测试 | 执行 Unit Test | 必须 |
| FR-TEST-03 | 集成测试 | 执行 Integration Test | 必须 |
| FR-TEST-04 | 构建与静态检查 | 执行 Build、Lint、Static Analysis | 必须 |
| FR-TEST-05 | 结果分析 | 执行 Test Result Analysis，定位失败用例 | 必须 |
| FR-TEST-06 | 结构化输出 | 输出 passed、summary（total/passed/failed）、failures 结构化结果 | 必须 |

### 3.16 代码审查（Reviewer Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-REV-01 | 职责界定 | Reviewer 验证"实现是否正确"，与 Test Agent（验证能否运行）分离 | 必须 |
| FR-REV-02 | 验收核对 | 检查是否满足 Acceptance Criteria | 必须 |
| FR-REV-03 | 架构一致性 | 检查是否违反架构设计 | 必须 |
| FR-REV-04 | 缺陷检查 | 识别潜在 Bug | 必须 |
| FR-REV-05 | 安全检查 | 检查是否存在安全问题 | 必须 |
| FR-REV-06 | 复杂度与影响面 | 检查是否引入不必要复杂度、是否影响现有模块、是否需要补充测试 | 应当 |
| FR-REV-07 | 结构化输出 | 输出 approved 与 issues（severity / file / line / problem / suggestion） | 必须 |

### 3.17 自纠错闭环（Self-correction Loop）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-FIX-01 | Test Loop | 形成 Coding → Testing → PASS? →（NO: Fix / YES: Review）循环 | 必须 |
| FR-FIX-02 | Review Loop | 形成 Reviewer → Approved? →（NO: Fix / YES: Finish）循环 | 必须 |
| FR-FIX-03 | 重试上限 | 设置 MAX_CODE_RETRY、MAX_TEST_RETRY、MAX_REVIEW_RETRY | 必须 |
| FR-FIX-04 | 超限转人工 | 超过阈值后必须转入 Human Intervention | 必须 |
| FR-FIX-05 | Reflexion 质量门 | 修复提交前进行自我批判，形成 Self-Reflection → Test → Review 三层质量门（V2） | 应当 |

### 3.18 Git 工作区隔离（Worktree）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-GIT-01 | 工作区隔离 | 并行 Agent 不共享同一工作目录，每任务使用独立 worktree/task-Tn 与 branch/agent-Tn | 应当 |
| FR-GIT-02 | 独立提交流程 | 每个 Coding Agent 流程：Task → Own Worktree → Own Branch → Patch → Commit | 应当 |
| FR-GIT-03 | 基础 Git 能力 | 支持 git_status / git_diff / git_log / git_branch / git_commit 操作 | 必须 |

### 3.19 集成合并（Integration Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-INTG-01 | 多分支合并 | 多个并行任务完成后由 Integration Agent 执行 Merge | 可选 |
| FR-INTG-02 | 冲突检测 | 执行 Conflict Detection | 可选 |
| FR-INTG-03 | 冲突解决 | 执行 Conflict Resolution（不重新实现业务逻辑） | 可选 |
| FR-INTG-04 | 集成测试 | 合并后执行 Full Test | 可选 |

### 3.20 代码检索（Code RAG）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-RAG-01 | 数据来源 | 支持 Source Code、README、Architecture Docs、API Docs、Git History、Issues、Pull Requests、Coding Standards 入库 | 应当 |
| FR-RAG-02 | 混合检索 | Query 同时经过 BM25 与 Dense Retrieval | 应当 |
| FR-RAG-03 | 结果融合 | 使用 RRF 融合多路检索结果 | 应当 |
| FR-RAG-04 | 精排 | 使用 Reranker 对融合结果重排 | 应当 |
| FR-RAG-05 | 符号检索 | 支持 Symbol Search（class / function / method / import / call relationship） | 应当 |
| FR-RAG-06 | 三路合成 | 形成 Lexical Retrieval + Semantic Retrieval + Symbol Retrieval 的完整检索能力 | 应当 |
| FR-RAG-07 | 上下文供给 | 检索结果以 Relevant Code Context 形式供给 Coding Agent | 应当 |

### 3.21 研究支持（Research Agent）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-RES-01 | 触发流程 | 当 Coding / Architect 缺少外部知识时，经 Supervisor 路由至 Research Agent | 应当 |
| FR-RES-02 | 资料来源优先 | 优先使用 Official Documentation、Official GitHub、API Reference | 应当 |
| FR-RES-03 | 结构化研究结果 | 输出 Structured Research Result 并回传请求方 Agent | 应当 |
| FR-RES-04 | 禁止盲目生成 | 缺少外部知识时必须经由 Research Agent 查询官方资料，不允许无限猜测 | 应当 |

### 3.22 共享状态（Shared State）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-STATE-01 | 统一状态结构 | 定义统一 DevState，供所有 Agent 读写 | 必须 |
| FR-STATE-02 | 字段完整 | 包含 project_id、user_request、requirements、architecture、task_dag、ready_tasks、current_tasks、completed_tasks、changed_files、commits、test_results、review_results、current_agent、iteration、retry_count、errors、run_status | 必须 |
| FR-STATE-03 | 大产物引用制 | 大型产物只保存引用（artifact_id / file_path / database_id） | 必须 |
| FR-STATE-04 | 防膨胀 | Shared State 不保存无限文本，避免无限增长 | 必须 |
| FR-STATE-05 | 状态驱动协作 | Agent 间通过 Structured Output → Shared State 协作，不依赖自由聊天 | 必须 |

### 3.23 记忆系统（Memory Architecture）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-MEM-01 | 工作记忆 | Working Memory 保存当前 Agent 的 Current Task、Recent Tool Calls、Recent Errors、Current Plan | 必须 |
| FR-MEM-02 | 项目记忆 | Project Memory 保存 Requirements、Architecture、Task Status、Coding Conventions、Important Decisions | 必须 |
| FR-MEM-03 | 长期记忆 | Long-term Memory 保存 Architecture Decision Records、Common Project Patterns、Frequently Seen Errors、Stable User Preferences | 应当 |
| FR-MEM-04 | 记忆装配 | 记忆经 ContextManager 装配后注入模型调用 | 必须 |
| FR-MEM-05 | 跨任务复用 | 长期记忆支持跨任务知识复用 | 应当 |

### 3.24 LangGraph 图设计

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-LG-01 | 分层图结构 | 采用 Main Graph + Development SubGraph + Coding SubGraph 三级结构 | 必须 |
| FR-LG-02 | Main Graph | 流程：START → Load Project → Supervisor → Product → Architect → Development SubGraph → Final Review → Human Approval → END | 必须 |
| FR-LG-03 | 动态跳转 | 实际执行非固定路线，Supervisor 可通过 Conditional Edge 动态跳转 | 应当 |
| FR-LG-04 | Development SubGraph | Task Scheduler → Detect Ready Tasks → Parallel Coding Agents → Integration → Testing →（Failed: Repair / Passed: Review → Return） | 应当 |
| FR-LG-05 | Coding SubGraph | Receive Task → Retrieve Context → Explore Repository → Generate Plan → Edit Code → Run Validation →（NO: Repair / YES: Finish） | 必须 |
| FR-LG-06 | 图元素支持 | 使用 StateGraph、Conditional Edge、Command、SubGraph、Checkpoint、Interrupt 构建动态 Agent Workflow | 必须 |

### 3.25 检查点与恢复（Checkpoint & Recovery）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-CKPT-01 | 关键节点保存 | 每个关键节点后保存 State + Current Agent + Task Status + Tool Results | 应当 |
| FR-CKPT-02 | 故障恢复 | 故障后 Load Last Checkpoint → Resume | 应当 |
| FR-CKPT-03 | 不从零重启 | 恢复不得从需求分析重新开始 | 应当 |
| FR-CKPT-04 | 长任务支持 | 支持软件开发长任务的状态持久化 | 应当 |
| FR-CKPT-05 | 恢复一致性 | 恢复后状态、任务与工具结果保持一致 | 应当 |

### 3.26 MCP 集成

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-MCP-01 | 统一连接 | 第三方工具通过 MCP 统一连接（GitHub / Jira / Documentation / Database / Search MCP） | 应当 |
| FR-MCP-02 | 链路结构 | Agent → Harness → MCP Client → MCP Server → External Service | 应当 |
| FR-MCP-03 | 职责分层 | MCP 属于 Tool connectivity layer，Harness 属于 Agent runtime layer，二者职责分离 | 应当 |

### 3.27 可观测性（Observability）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-OBS-01 | 全链路追踪 | 所有 Agent Run 可追踪：Project Run → Supervisor → Architect → Coding Agent（工具子节点）→ Tester → Reviewer | 必须 |
| FR-OBS-02 | 记录项 | 记录 model、agent、tool、latency、token usage、cost、tool result、error、retry count、sandbox usage | 必须 |
| FR-OBS-03 | 追踪管理 | 由 TraceManager 统一采集与上报 | 必须 |
| FR-OBS-04 | 追踪系统接入 | 集成 LangSmith 与 OpenTelemetry | 应当 |
| FR-OBS-05 | 监控看板 | 接入 Prometheus + Grafana | 应当 |

### 3.28 评测体系（Evaluation）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-EVAL-01 | Task Success | 统计任务是否完成 | 应当 |
| FR-EVAL-02 | Test Pass Rate | 统计最终测试通过率 | 应当 |
| FR-EVAL-03 | First-pass Success Rate | 统计第一次 Coding 后直接通过 Test/Review 的比例 | 应当 |
| FR-EVAL-04 | Retry Count | 统计平均修复次数 | 应当 |
| FR-EVAL-05 | Patch Correctness | 评估 Patch 是否正确解决问题 | 应当 |
| FR-EVAL-06 | Regression Rate | 统计是否破坏已有功能 | 应当 |
| FR-EVAL-07 | Agent Routing Accuracy | 评估 Supervisor 是否选择正确的 Agent | 应当 |
| FR-EVAL-08 | Cost | 统计 Tokens、API Cost、Tool Calls、Execution Time | 必须 |
| FR-EVAL-09 | Regression Suite | 维护 Golden Set（固定评测任务集合）并支持 Offline Regression 离线回归评测，与 DSPy 优化（V3）共享数据 | 应当 |

### 3.29 后端服务（Backend）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-API-01 | 创建项目 | POST /projects | 必须 |
| FR-API-02 | 创建运行 | POST /projects/{id}/runs | 必须 |
| FR-API-03 | 查询运行 | GET /runs/{id} | 必须 |
| FR-API-04 | 查询状态 | GET /runs/{id}/state | 必须 |
| FR-API-05 | 事件流 | GET /runs/{id}/events | 必须 |
| FR-API-06 | 恢复运行 | POST /runs/{id}/resume | 必须 |
| FR-API-07 | 查询任务 | GET /runs/{id}/tasks | 必须 |
| FR-API-08 | 查询变更 | GET /runs/{id}/diff | 必须 |
| FR-API-09 | 人工审批 | POST /runs/{id}/approve | 必须 |

### 3.30 实时流式推送（Streaming）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-SSE-01 | SSE 推送 | 客户端通过 SSE 接收运行事件流 | 应当 |
| FR-SSE-02 | 事件内容 | 推送规划、任务生成、任务就绪、Agent 启动、工具调用、测试结果、修复、审查结果等事件 | 应当 |
| FR-SSE-03 | 准实时体验 | 事件应实时展示（如 Supervisor analyzing / 52 tests passed / Reviewer approved） | 应当 |

### 3.31 桌面客户端（Desktop Client）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-UI-01 | 技术形态 | Tauri 2 + React，打包为 exe / msi，无浏览器依赖；MVP 阶段以 CLI / API 验证流程，客户端随 V2 交付 | 应当 |
| FR-UI-02 | 组件选型 | React Flow（DAG 拓扑）、Monaco Editor（Diff 高亮）、Tailwind CSS（深色主题）、Recharts（Token / 成本图表） | 应当 |
| FR-UI-03 | 界面布局 | 四区布局：Project Header + 左侧 Task DAG + 中间 Agent Trace + 右侧 Diff Viewer + 底部 Approval Panel | 应当 |
| FR-UI-04 | Project Dashboard | 展示 Project、Repository、Current Run、Current Agent、Task DAG、Agent Timeline、Cost | 应当 |
| FR-UI-05 | Task DAG 可视化 | 节点实时变色：Pending / Running / Completed / Failed / Blocked | 应当 |
| FR-UI-06 | 轨迹与 Diff | Agent Trace 展示工具调用序列；Diff Viewer 展示最终 Patch 与逐文件 Diff | 应当 |
| FR-UI-07 | 审批面板 | 支持 Commit / Push / Merge / Deploy 审批操作 | 应当 |

### 3.32 智能层增强（对应设计方案第 45 节）

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-INTEL-01 | A2A 互操作 | 采用 A2A 协议与外部 Agent 平台互操作，与 MCP 组成双协议栈 | 应当 |
| FR-INTEL-02 | 能力暴露 | 以 Agent Card 形式对外暴露本系统能力，支持接收外部 Task 并返回结构化结果 | 应当 |
| FR-INTEL-03 | Agent Skills | 将能力封装为按需动态加载的技能包（SKILL.md），由 ContextManager 装配 | 应当 |
| FR-INTEL-04 | Agentic RAG | 检索策略 Agent 自主选择策略（向量 / BM25 / 符号 / 图 / 多跳）并自检结果充分性 | 应当 |
| FR-INTEL-05 | GraphRAG | AST / 符号解析（tree-sitter）构建代码知识图谱，图检索 + 向量检索混合 | 可选 |
| FR-INTEL-06 | Reflexion | 修复提交前自我批判（是否真正解决根因？影响面是否完整？） | 应当 |
| FR-INTEL-07 | 输入护栏 | 检测 Prompt Injection、恶意指令与越权请求 | 应当 |
| FR-INTEL-08 | 输出护栏 | 输出 JSON Schema 校验与敏感信息泄漏检测 | 应当 |
| FR-INTEL-09 | 护栏联动审批 | 护栏拦截事件升级至人工审批 | 应当 |
| FR-INTEL-10 | DSPy 优化 | 基于评测集（Golden Set）与运行数据对 Agent 指令链路进行程序化优化 | 可选 |

验收要点：

- A2A 边界适配不破坏内部 Shared State + 结构化协议
- 护栏拦截路径具备放行 / 拦截 / 转审批三级结果

---

## 4. 非功能需求

### 4.1 性能

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-PERF-01 | 长任务支持 | 支持软件开发长任务（多步骤流程）持续执行 | 必须 |
| NFR-PERF-02 | 上下文预算控制 | 通过最小上下文、Compaction 与 Token 压缩控制上下文规模 | 必须 |
| NFR-PERF-03 | 事件推送延迟 | SSE 事件准实时推送（秒级体验） | 应当 |
| NFR-PERF-04 | 并行加速 | 无依赖任务并行执行，缩短总任务时长 | 应当 |
| NFR-PERF-05 | 成本预算约束 | 通过 max_cost、max_tokens 等停止条件约束单次运行成本 | 必须 |

### 4.2 安全

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-SEC-01 | 执行隔离 | 所有代码执行在沙箱内完成，默认禁访主机文件系统、SSH Key、生产数据库、云凭证、私有环境变量 | 必须 |
| NFR-SEC-02 | 最小权限 | 基于 Capability Profile 为不同 Agent 提供最小权限执行环境 | 必须 |
| NFR-SEC-03 | Secret 隔离 | 凭证与密钥不暴露给沙箱内执行代码 | 必须 |
| NFR-SEC-04 | 高风险审批 | 高风险与关键操作强制人工审批 | 必须 |
| NFR-SEC-05 | 语义安全护栏 | 检测与拦截 Prompt Injection、越权指令与敏感信息泄漏（V2） | 应当 |

### 4.3 可靠性与恢复

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-REL-01 | 检查点恢复 | 故障后可从最近 Checkpoint 恢复，不从头重跑 | 应当 |
| NFR-REL-02 | 重试上限 | 测试与审查循环有明确上限，超限转人工 | 必须 |
| NFR-REL-03 | 防无限循环 | 执行循环必须配置完整停止条件 | 必须 |
| NFR-REL-04 | 状态一致性 | 恢复或重试后 Shared State 保持一致 | 必须 |

### 4.4 可扩展性

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-SCALE-01 | Agent 可扩展 | 新增 Agent 复用统一 Harness，不改动编排框架 | 必须 |
| NFR-SCALE-02 | 工具可扩展 | 工具通过 ToolRegistry 注册扩展，外部能力经 MCP / A2A 接入 | 必须 |
| NFR-SCALE-03 | LLM 可替换 | 支持 OpenAI / Claude / Gemini / Local Models 配置化切换 | 必须 |
| NFR-SCALE-04 | 存储可扩展 | 向量库支持 pgvector / Qdrant / OpenSearch 等选项 | 应当 |
| NFR-SCALE-05 | Agent 团队扩展 | V3 可扩展 Frontend / Backend / Database / Security / DevOps Agent | 可选 |

### 4.5 可维护性

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-MAINT-01 | 运行时复用 | 统一 Harness 复用，避免多 Agent 重复实现 | 必须 |
| NFR-MAINT-02 | 配置化 | Capability Profile、Policy、重试上限、停止条件、沙箱规格可配置 | 必须 |
| NFR-MAINT-03 | 目录规范 | 按设计方案第 41 节推荐代码目录组织工程 | 应当 |
| NFR-MAINT-04 | 文档同步 | 设计、接口与部署文档随代码同步维护 | 应当 |

### 4.6 兼容性

| 编号 | 需求名称 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| NFR-COMPAT-01 | 跨平台 | 客户端跨平台打包（Tauri），沙箱依赖 Docker 跨平台运行 | 必须 |
| NFR-COMPAT-02 | 目标项目兼容 | 以 Python 项目为主要目标，架构上兼容多语言扩展 | 必须 |
| NFR-COMPAT-03 | Git 平台兼容 | 兼容 GitHub 等主流平台（经 MCP 接入） | 应当 |

---

## 5. 接口需求

### 5.1 后端 REST API

| 编号 | 接口 | 说明 |
|------|------|------|
| IR-01 | POST /projects | 创建项目 |
| IR-02 | POST /projects/{id}/runs | 启动一次运行 |
| IR-03 | GET /runs/{id} | 查询运行信息 |
| IR-04 | GET /runs/{id}/state | 查询共享状态 |
| IR-05 | GET /runs/{id}/events | 事件流（SSE） |
| IR-06 | POST /runs/{id}/resume | 审批 / 中断后恢复 |
| IR-07 | GET /runs/{id}/tasks | 查询任务列表 |
| IR-08 | GET /runs/{id}/diff | 查询代码变更 |
| IR-09 | POST /runs/{id}/approve | 提交人工审批结果 |

### 5.2 事件流接口（SSE）

| 编号 | 接口 | 说明 |
|------|------|------|
| IR-10 | SSE 事件流 | 推送运行事件，示例：Supervisor analyzing project... / Architect generated 6 tasks. / Coding Agent started T1. / edit_file("src/auth.py") / 2 tests failed. / Repairing... / 52 tests passed. / Reviewer approved. |

### 5.3 MCP 接口

| 编号 | 接口 | 说明 |
|------|------|------|
| IR-11 | MCP 接入 | Agent → Harness → MCP Client → MCP Server → External Service（GitHub / Jira / Documentation / Database / Search） |

### 5.4 A2A 接口（V2）

| 编号 | 接口 | 说明 |
|------|------|------|
| IR-12 | A2A 互操作 | 以 Agent Card 对外暴露能力，接收外部 Agent 的 Task 请求并返回结构化结果；边界适配由 Harness 承载 |

### 5.5 Agent 结构化通信协议

| 编号 | 接口 | 说明 |
|------|------|------|
| IR-13 | 结构化通信 | Agent 间使用 Pydantic + JSON Schema + Structured Output 交换结构化产物，禁止依赖自由文本聊天 |

---

## 6. 数据需求

### 6.1 共享状态（DevState）字段

| 编号 | 字段 | 类型 | 说明 |
|------|------|------|------|
| DR-01 | project_id | str | 项目标识 |
| DR-02 | user_request | str | 用户原始需求 |
| DR-03 | requirements | dict | 结构化产品需求 |
| DR-04 | architecture | dict | 技术设计结果 |
| DR-05 | task_dag | list | 任务 DAG |
| DR-06 | ready_tasks | list | 就绪任务 |
| DR-07 | current_tasks | list | 进行中任务 |
| DR-08 | completed_tasks | list | 已完成任务 |
| DR-09 | changed_files | list | 变更文件 |
| DR-10 | commits | list | 提交记录 |
| DR-11 | test_results | dict | 测试结果 |
| DR-12 | review_results | dict | 审查结果 |
| DR-13 | current_agent | str | 当前执行 Agent |
| DR-14 | iteration | int | 迭代计数 |
| DR-15 | retry_count | int | 重试计数 |
| DR-16 | errors | list | 错误记录 |
| DR-17 | run_status | str | 运行状态 |

### 6.2 大产物引用

| 编号 | 引用方式 | 说明 |
|------|----------|------|
| DR-18 | artifact_id | 产物标识引用 |
| DR-19 | file_path | 文件路径引用 |
| DR-20 | database_id | 数据库记录引用 |

### 6.3 记忆分层

| 层级 | 内容 |
|------|------|
| Working Memory | Current Task / Recent Tool Calls / Recent Errors / Current Plan |
| Project Memory | Requirements / Architecture / Task Status / Coding Conventions / Important Decisions |
| Long-term Memory | Architecture Decision Records / Common Project Patterns / Frequently Seen Errors / Stable User Preferences |

### 6.4 数据库（PostgreSQL）

需存储的数据表：

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

### 6.5 缓存（Redis）

```text
temporary state
cache
event stream
task coordination
```

### 6.6 向量库

存储内容：code embedding、documentation embedding、project memory。

可选技术：pgvector / Qdrant / OpenSearch。

### 6.7 数据安全

- 审批（approvals）、审查（reviews）与运行记录（runs / agent_runs / tool_runs）留痕，可审计
- 凭证与密钥不进入沙箱与执行代码（Secret Isolation）
- Shared State 仅保存结构化结论与大产物引用，避免敏感大数据进入状态

---

## 7. 约束与假设

### 7.1 技术约束

- 依赖 LangGraph 能力：StateGraph、Conditional Edge、Command、SubGraph、Checkpoint、Interrupt
- 受 LLM 能力上限影响（长上下文、结构化输出质量）
- 所有代码执行依赖 Docker 环境
- 并行工作区隔离依赖 Git Worktree
- 桌面客户端依赖 Tauri 2 工具链

### 7.2 假设

- 用户可提供可访问的代码仓库与可运行的测试框架
- LLM API 可用且额度满足运行需要
- 目标项目的构建、测试可通过命令行驱动

### 7.3 外部依赖

- 第三方 LLM 服务（OpenAI / Claude / Gemini / Local Models）
- Docker 运行环境
- PostgreSQL、Redis、向量数据库
- MCP Server 生态（GitHub、Jira、Documentation、Database、Search）
- 可观测性体系（LangSmith / OpenTelemetry / Prometheus / Grafana）

---

## 8. 验收标准

### 8.1 MVP 端到端验收场景

前提：给定一个代码仓库与一条自然语言开发需求。

1. Product Agent 输出结构化需求（features / user_stories / acceptance_criteria / non_functional_requirements / open_questions）
2. Architect Agent 输出技术设计与任务列表（含依赖关系）
3. Coding Agent 完成代码修改，并在 Coding SubGraph 中通过验证（沙箱内执行）
4. Test Agent 输出结构化测试结果（passed / summary / failures）
5. 测试失败时自动进入修复循环且不超上限；超限转人工介入
6. Reviewer Agent 输出结构化审查结果；不通过时修改后复审
7. 生成 Git Diff → Human Approval；通过后可提交（push / 部署类强制审批）
8. 基础 Harness 就绪：ContextManager、ToolRegistry、ToolExecutor、PermissionManager、Docker Sandbox、TraceManager
9. 全流程可追踪（Agent / 工具 / 成本 / 重试），运行状态与任务可通过 API 查询

### 8.2 量化验收指标（Evaluation 基线）

验收时必须能够采集并报告以下指标：

- Task Success
- Test Pass Rate
- First-pass Success Rate
- Retry Count
- Patch Correctness
- Regression Rate
- Agent Routing Accuracy
- Cost（Tokens / API Cost / Tool Calls / Execution Time）

### 8.3 需求级验收

- 所有“必须”级需求全部实现并通过测试
- “应当”级需求按 V2 里程碑分批验收
- 异常路径（测试失败、审查拒绝、重试超限、审批拒绝、停止条件触发）均有可验证的确定性行为

---

## 9. 版本规划

### 9.1 MVP

流程：User → Product Agent → Architect Agent → Coding Agent → Test Agent → Reviewer Agent → Git Diff → Human Approval。

基础 Harness：ContextManager、ToolRegistry、ToolExecutor、PermissionManager、Docker Sandbox、TraceManager。

工具：read_file、search_code、edit_file、git_diff、run_test。

MVP 不做：Parallel Agent、MCP、Long-term Memory、Complex RAG、Automatic Git Push、Deployment。

说明：MVP 阶段由 Supervisor 以固定顺序调度；V2 起升级为基于 Shared State 的动态路由。

### 9.2 V2

- Supervisor Dynamic Routing
- Code RAG（含 Agentic RAG）
- Task DAG
- Parallel Coding Agents
- Git Worktree
- Checkpoint
- Research Agent
- MCP + A2A
- Agent Skills
- Context Engineering
- Reflexion
- Guardrails
- HITL
- SSE Streaming
- Desktop Client（Tauri 2 + React）

### 9.3 V3

- Frontend Agent / Backend Agent / Database Agent / Security Agent / DevOps Agent / Integration Agent
- Multi-repository Support
- PR Automation
- Long-term Project Memory
- Automatic Evaluation
- Agent Cost Optimization
- DSPy（指令链路程序化优化）
- GraphRAG（代码知识图谱）

### 9.4 智能层融入点

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

## 10. 风险分析

| 风险 | 说明 | 应对措施 |
|------|------|----------|
| LLM 输出不稳定 | 非结构化输出导致下游 Agent 无法解析 | 结构化输出（Pydantic / JSON Schema）+ 校验 + 重试 |
| 无限循环与成本失控 | Agent 循环不收敛，Token 消耗失控 | 停止条件（max_steps / max_tokens / max_cost / timeout）+ 重试上限 + Cost 监控 |
| 沙箱逃逸 | Agent 生成代码访问主机资源 | Docker 隔离 + 禁访清单 + Secret 隔离 |
| 上下文溢出 | 长任务上下文超限 | 最小必要上下文 + Compaction + Observation Adapter 压缩 + Code RAG |
| 并行修改冲突 | 多 Agent 同时修改同一目录 | Git Worktree 隔离 + Integration Agent 合并 |
| 需求歧义 | 需求模糊导致返工 | open_questions 澄清 + 需求冲突/缺失发现 |
| 高风险误操作 | 删除/推送/部署等误执行 | Policy Engine 风险分级 + 强制审批 + interrupt() |
| 环境差异 | 测试结果与预期不一致 | 沙箱内统一环境执行 |

---

## 11. 需求追踪矩阵

| 设计方案章节 | 对应需求编号 |
|--------------|--------------|
| 1. 项目概述 | 第 2 章项目总体描述 |
| 2. 核心设计原则 | 2.6 核心设计原则、第 4 章非功能需求 |
| 3. 总体系统架构 | 2.7 分层架构 |
| 4. Supervisor Agent | FR-SUP-01 ~ FR-SUP-09 |
| 5. Product Agent | FR-PROD-01 ~ FR-PROD-06 |
| 6. Architect Agent | FR-ARCH-01 ~ FR-ARCH-06 |
| 7. Task DAG | FR-TASK-01 ~ FR-TASK-06 |
| 8. Coding Agent | FR-CODE-01 ~ FR-CODE-09 |
| 9. Unified Agent Harness | FR-HARNESS-01 ~ FR-HARNESS-06 |
| 10. Context Manager | FR-CTX-01 ~ FR-CTX-05 |
| 11. Tool Registry | FR-TOOL-01 ~ FR-TOOL-07 |
| 12. Tool Definition | FR-TOOL-02 |
| 13. Capability Profile | FR-CAP-01 ~ FR-CAP-05 |
| 14. Policy Engine | FR-POL-01 ~ FR-POL-05 |
| 15. Human-in-the-loop | FR-HITL-01 ~ FR-HITL-06 |
| 16. Sandbox | FR-SB-01 ~ FR-SB-05 |
| 17. Observation Adapter | FR-OBSA-01 ~ FR-OBSA-05 |
| 18. Agent Execution Loop | FR-EXEC-01 ~ FR-EXEC-04 |
| 19. Test Agent | FR-TEST-01 ~ FR-TEST-06 |
| 20. Reviewer Agent | FR-REV-01 ~ FR-REV-07 |
| 21. Self-correction Loop | FR-FIX-01 ~ FR-FIX-05 |
| 22. Git Workspace Isolation | FR-GIT-01 ~ FR-GIT-03 |
| 23. Integration Agent | FR-INTG-01 ~ FR-INTG-04 |
| 24. Code RAG | FR-RAG-01 ~ FR-RAG-07 |
| 25. Research Agent | FR-RES-01 ~ FR-RES-04 |
| 26. Shared State | FR-STATE-01 ~ FR-STATE-05、DR-01 ~ DR-20 |
| 27. Memory Architecture | FR-MEM-01 ~ FR-MEM-05、6.3 节 |
| 28~31. LangGraph 设计（Main / Development / Coding） | FR-LG-01 ~ FR-LG-06 |
| 32. Checkpoint & Recovery | FR-CKPT-01 ~ FR-CKPT-05 |
| 33. MCP Integration | FR-MCP-01 ~ FR-MCP-03、IR-11 |
| 34. Observability | FR-OBS-01 ~ FR-OBS-05 |
| 35. Evaluation | FR-EVAL-01 ~ FR-EVAL-09 |
| 36. Backend Architecture | FR-API-01 ~ FR-API-09、IR-01 ~ IR-09 |
| 37. Streaming | FR-SSE-01 ~ FR-SSE-03、IR-10 |
| 38. Desktop Client | FR-UI-01 ~ FR-UI-07 |
| 39. Storage | 第 6 章数据需求（6.4 ~ 6.6 节） |
| 40. 推荐技术栈 | 2.8 运行环境与技术栈、NFR-SCALE |
| 41. 推荐代码目录 | NFR-MAINT-03 |
| 42. MVP | 9.1 版本规划、8.1 验收场景 |
| 43. V2 | 9.2 版本规划 |
| 44. V3 | 9.3 版本规划 |
| 45. 智能层增强技术 | FR-INTEL-01 ~ FR-INTEL-10、IR-12、9.4 节 |
| 46~49. 关键创新点 / MetaGPT 对比 / 最终定位 / 简历描述 | 叙事性章节，不产生独立需求 |
