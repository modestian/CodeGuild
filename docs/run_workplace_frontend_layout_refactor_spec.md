# Frontend Layout Refactor Specification

## 1. 目标

对当前已实现的 Agent 开发平台前端进行 **UI/UX Layout Refactor**。

本次优化只针对：

- 页面排版
- 信息层级
- 空间分配
- 视觉密度
- 字体层级
- 卡片与边框使用
- 交互区域组织
- 响应式布局

**不要修改：**

- 业务逻辑
- Agent 状态机
- API
- SSE 事件协议
- 任务执行逻辑
- LangGraph 流程
- 后端接口
- 数据结构

目标不是“重做一个新页面”，而是在现有功能基础上进行 **布局重构与视觉层级优化**。

---

# 2. 当前页面存在的问题

当前页面功能信息已经较完整，但存在明显的信息密度和视觉层级问题。

主要问题如下：

## 2.1 信息密度过高

页面同时展示：

- 顶部项目状态
- 大量操作按钮
- Task DAG
- Agent 执行日志
- AI 解说 / 交流
- 人工审批
- 文件变化
- 测试状态
- Review 状态

所有区域同时展开，导致用户第一眼无法快速判断：

1. 当前任务做到哪里
2. 为什么停止
3. 用户现在需要做什么

---

## 2.2 主次关系不清晰

目前：

- Task DAG
- Agent Activity
- AI Chat
- Human Approval
- 顶部按钮

视觉权重比较接近。

实际上页面应具有明显优先级：

```text
当前状态
    ↓
当前阶段
    ↓
当前异常 / 阻塞
    ↓
用户需要采取的操作
    ↓
详细日志
```

而不是所有信息同时抢占注意力。

---

## 2.3 顶部操作区域过于拥挤

当前 Header 包含大量：

- 状态标签
- Run ID
- Cost
- Token
- 自动模式
- Diff
- 产出物
- 留痕
- 指标
- 刷新
- Theme
- Stop

按钮数量过多。

建议：

### 左侧保留

- 返回项目
- 项目名
- 当前 Run 状态
- 当前阶段

### 右侧保留核心操作

建议只直接展示：

- Run ID
- Cost / Token
- 自动 / 手动
- Stop
- More

以下操作收进 `More / ···`：

- Diff
- 产出物
- 留痕
- 指标
- 刷新
- 其他低频功能

---

# 3. 页面核心设计目标

用户进入页面后，应能在 3~5 秒内回答：

```text
1. 现在做到哪里？
2. 为什么停了？
3. 我现在需要做什么？
```

页面设计必须围绕这三个问题展开。

---

# 4. 推荐总体布局

保留三栏结构，但重新分配空间。

```text
┌──────────────────────────────────────────────────────────────┐
│ noteapp     HUMAN_APPROVAL            Cost / Token / Actions │
│ 当前需求：添加一个依赖说明文件                               │
├──────────────┬──────────────────────────────┬────────────────┤
│              │                              │                │
│   TASK DAG   │       AGENT ACTIVITY         │   AI / CHAT    │
│              │                              │                │
│              │                              │                │
│              │                              │                │
│              │                              │                │
├──────────────┴──────────────────────────────┴────────────────┤
│ Contextual Human Approval Panel / Current Blocking Action    │
└──────────────────────────────────────────────────────────────┘
```

建议尺寸：

```text
Task DAG:
280px ~ 320px

AI / Chat:
340px ~ 380px

Agent Activity:
flex: 1
```

三栏建议支持：

```text
Resizable Panes
```

即用户可以拖动左右宽度。

---

# 5. Task DAG 优化

当前 DAG 卡片信息过多，更像“小文档卡片”，而不是任务图。

## 5.1 DAG 节点只保留核心内容

每个节点显示：

```text
T5
依赖扫描验证
Failed
Retry 3/3
```

不要在节点直接展示过长任务描述。

长内容应放入：

```text
Task Detail Drawer
```

点击节点后展示：

- 完整任务描述
- Dependencies
- Agent
- Retry
- Changed Files
- Test Result
- Review Result
- Error

---

## 5.2 状态颜色统一

仅保留明确语义：

```text
Green  = Success
Red    = Failed / Blocked
Amber  = Waiting / Human Approval
Blue   = Running / Information
Gray   = Pending
```

不要使用 Agent 类型颜色区分。

---

## 5.3 DAG 卡片减少装饰

避免：

- 大量阴影
- 过大圆角
- 多层边框
- 过多 Badge

优先通过：

- border
- background
- typography
- spacing

表达状态。

---

# 6. Agent Activity 优化

Agent Activity 是整个页面的主区域。

当前问题：

- 每一条日志视觉权重接近
- started / finished / validation 等事件大量重复
- 用户难以快速理解阶段变化

建议改成：

# Hierarchical Timeline

例如：

```text
Supervisor
├─ analyzed project
└─ routed to development

Coding Agent · T5
├─ started
├─ inspected repository
├─ attempted implementation
└─ stopped: max_tokens reached

Validation
└─ failed

Retry 1
└─ ...

Retry 2
└─ ...

Retry 3
└─ failed

Human Approval Required
```

---

## 6.1 一级事件

重点显示：

- Supervisor Decision
- Task Started
- Coding Phase
- Validation
- Test
- Review
- Retry
- Human Approval
- Task Completed
- Task Failed

---

## 6.2 二级事件默认折叠

以下事件默认作为详情：

```text
agent_started
agent_finished
tool_started
tool_finished
approval_received
internal status updates
```

不要全部平铺。

用户可点击：

```text
Show details
```

查看底层事件。

---

## 6.3 重要事件突出

只有以下事件使用强调背景：

### Error

```text
Red / subtle red background
```

### Warning / Retry

```text
Amber
```

### Human Approval

```text
Amber + action emphasis
```

### Success

```text
Green
```

普通日志：

```text
无 Card
无大面积边框
```

采用简单 timeline row 即可。

---

# 7. AI Chat / AI Explanation 优化

当前右侧每条内容都采用独立卡片，导致页面碎片化。

建议改成：

```text
Timeline / Message Stream
```

普通事件：

```text
● 发现问题，进入修复循环
  10:32:01 · Developer Agent
```

关键事件才使用容器：

```text
⚠ Task T5 Failed
Reached MAX_CODE_RETRY = 3
```

---

## 7.1 AI 交流区分两种内容

### System Explanation

展示：

- 当前发生什么
- 为什么发生
- 下一步准备做什么

### Human Chat

展示：

- 用户输入
- Agent 回复
- 用户补充需求

不要将两者完全混成相同卡片。

---

# 8. Human Approval 区域重构

当前底部审批区域长期占据大量页面高度。

建议改为：

# Contextual Approval Panel

只在以下情况出现：

```text
run_status == HUMAN_APPROVAL
```

正常运行时：

```text
隐藏
```

---

## 8.1 推荐样式

```text
┌─────────────────────────────────────────────────────────────┐
│ ⚠ T5 已失败 3 次，需要人工决定                              │
│                                                             │
│ 原因：Reached MAX_CODE_RETRY = 3                            │
│                                                             │
│ [继续修复]   [查看 Diff]   [补充指令]   [拒绝任务]          │
└─────────────────────────────────────────────────────────────┘
```

建议：

- 固定在底部
- 高度自适应
- 最大高度约 240~320px
- 支持展开详细信息

---

## 8.2 审批操作优先级

主操作：

```text
继续迭代
```

次操作：

```text
查看 Diff
补充指令
```

危险操作：

```text
拒绝 / 终止
```

危险按钮才使用红色。

---

# 9. Typography

建立明确字体层级。

建议：

```text
Page Title:
16~18px / 600

Section Title:
13~14px / 600

Primary Content:
13~14px / 400~500

Metadata:
11~12px / 400

Code / Event Type:
12px monospace
```

避免所有：

```text
Agent Label
Status
Event Type
Metadata
```

都使用 Badge。

Badge 只用于真正状态。

---

# 10. Spacing System

统一使用：

```text
4px / 8px spacing system
```

推荐 Token：

```text
4px   xs
8px   sm
12px  md-small
16px  md
24px  lg
32px  xl
```

页面区域之间：

```text
24px ~ 32px
```

组件内部：

```text
8px ~ 16px
```

---

# 11. Alignment

重点检查：

- Section Title 左边缘
- Timeline 内容左边缘
- DAG 节点文字
- Chat 内容
- Header 内容

页面应形成稳定的视觉基线。

避免不同模块出现：

```text
17px
21px
13px
```

这种无规律 padding。

---

# 12. Border / Card 使用规则

当前页面 Card 和 Border 数量过多。

调整原则：

```text
Layout → 用 spacing 区分
Section → 用 background 区分
Component → 必要时使用 border
Status → 用颜色 / icon 区分
```

避免：

```text
Card inside Card inside Card
```

---

# 13. 圆角

统一 Radius：

```text
Small:
6px

Medium:
8px

Large:
10px
```

不要不同区域随机使用：

```text
6 / 8 / 10 / 12 / 16px
```

---

# 14. Shadow

开发者工具类产品不需要大量阴影。

原则：

```text
默认：
无阴影

浮层：
轻微阴影

Modal / Drawer：
适度阴影
```

---

# 15. 页面视觉风格

目标风格：

```text
Developer Tool
AI Engineering Console
Clean
Dense but readable
Professional
Technical
Calm
```

避免：

```text
Marketing Landing Page
Dribbble Dashboard
Heavy Gradient
Glassmorphism
Huge Radius
Excessive Shadow
Decorative Animation
Generic AI Purple UI
```

---

# 16. Responsive

## Desktop

使用三栏：

```text
Task DAG | Agent Activity | AI Chat
```

---

## Medium Screen

AI Chat 可折叠：

```text
Task DAG | Agent Activity
                    + Chat Drawer
```

---

## Small Screen

改为 Tab：

```text
[Tasks] [Activity] [Chat]
```

Human Approval 固定在底部。

---

# 17. 不允许修改的内容

本次重构禁止修改：

```text
Agent state machine
SSE protocol
Backend API
Event type
Task execution
Retry strategy
LangGraph logic
Database schema
```

如果前端组件依赖这些逻辑：

```text
只适配 UI
不要修改逻辑本身
```

---

# 18. 推荐执行流程

AI 必须按照以下顺序进行：

## Phase 1 — Audit

先分析：

- 当前 Layout
- 组件结构
- CSS / Tailwind
- Panel
- Header
- Timeline
- Approval
- DAG

输出：

```text
需要修改的组件
当前问题
修改目标
```

**不要立刻开始重写。**

---

## Phase 2 — Layout Refactor

先修改：

1. Header
2. 三栏尺寸
3. Human Approval
4. Agent Activity

这四项优先级最高。

---

## Phase 3 — Visual Hierarchy

调整：

- Typography
- Spacing
- Border
- Background
- Badge
- Color

---

## Phase 4 — Timeline Refactor

将 Agent Activity 从：

```text
Flat Event List
```

改为：

```text
Hierarchical Timeline
```

---

## Phase 5 — Responsive

检查：

```text
1440px
1280px
1024px
768px
```

---

## Phase 6 — Visual Review

完成代码后必须重新渲染页面并检查：

- 是否仍然过于拥挤
- 主区域是否足够突出
- Human Approval 是否清晰
- Task DAG 是否易读
- Event Timeline 是否易扫描
- Chat 是否仍然碎片化
- 是否存在 Overflow
- 是否出现不一致 spacing
- 是否出现不必要 Card
- 是否存在文字截断问题

如果发现问题：

```text
继续调整
```

不要第一次改完就结束。

---

# 19. 优先级

## P0

必须优先优化：

```text
1. Human Approval
2. Agent Activity
3. Header
4. 三栏比例
```

---

## P1

第二阶段：

```text
Task DAG
AI Chat
Typography
Spacing
```

---

## P2

最后：

```text
Responsive
Animation
Minor Polish
```

---

# 20. 推荐目标布局

最终希望呈现：

```text
┌────────────────────────────────────────────────────────────────┐
│ ← noteapp   HUMAN_APPROVAL        $2.00  5.9M     Auto    ··· │
│   添加一个依赖说明文件                                        │
├──────────────┬──────────────────────────────┬──────────────────┤
│ TASK DAG     │ AGENT ACTIVITY               │ AI / CHAT        │
│              │                              │                  │
│ T1 ✓         │ Supervisor                   │ 当前状态          │
│  ↓           │ └─ Routed to development     │                  │
│ T2 ✓         │                              │ T5 已失败         │
│  ↓           │ Coding Agent · T5            │ 原因：Token Limit │
│ T3 ✓         │ ├─ Started                   │                  │
│  ↓           │ ├─ Validation failed         │ 下一步：等待审批   │
│ T4 ✓         │ └─ Retry ×3                  │                  │
│  ↓           │                              │                  │
│ T5 ✕         │ Human Approval Required      │                  │
│              │                              │                  │
├──────────────┴──────────────────────────────┴──────────────────┤
│ ⚠ T5 重试次数已达上限                                         │
│ [继续迭代] [查看 Diff] [补充指令]                   [拒绝]     │
└────────────────────────────────────────────────────────────────┘
```

---

# 21. 验收标准

本次 UI Refactor 完成后，应满足：

- [ ] 用户 3~5 秒内能知道当前系统状态
- [ ] 能快速发现当前失败 / 阻塞原因
- [ ] Human Approval 操作明显
- [ ] Agent Activity 不再是大量平铺日志
- [ ] 普通日志不再使用大量 Card
- [ ] Task DAG 更像 DAG，而不是文档列表
- [ ] Header 操作明显减少
- [ ] 主内容区域获得最大视觉权重
- [ ] 页面不再大量依赖 Border 建立层级
- [ ] Typography 层级统一
- [ ] Spacing 使用统一尺度
- [ ] Desktop 页面无横向拥挤
- [ ] 1024px 下仍可正常使用
- [ ] 不修改现有业务逻辑
- [ ] 不修改后端 API
- [ ] 不修改 SSE 事件协议
- [ ] 不改变现有 Agent 执行流程

---

# 22. 给 Coding Agent 的最终要求

请基于现有代码进行 **增量式 UI Refactor**。

不要：

```text
重新生成整个项目
重新设计业务逻辑
修改 Agent workflow
随意删除现有功能
```

优先：

```text
Reuse Existing Components
Extract Layout Components
Refactor Styling
Improve Visual Hierarchy
Keep Existing Behavior
```

完成修改后：

```text
Render
→ Inspect
→ Fix
→ Render Again
```

至少进行一次完整 Visual Review 后再结束任务。
