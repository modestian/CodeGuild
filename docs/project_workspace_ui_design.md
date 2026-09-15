# Project Workspace UI Refactor Specification

## 1. 页面定位

本页面是 **Project Workspace / 项目工作台**，用于：

1. 查看当前注册的代码仓库
2. 选择目标仓库
3. 输入自然语言开发需求
4. 选择 Agent 执行模式
5. 发起新的开发任务
6. 查看历史 Run
7. 进入某次 Run 的详情页

> 本页面不是 Agent 执行监控页。  
> Agent 执行过程、Task DAG、Agent Timeline、Human Approval 等内容属于 `Run Workspace`。

---

# 2. 页面核心目标

用户进入页面后，应能快速完成两件事：

```text
A. 发起一个新的开发任务
B. 找到之前的开发任务并进入详情
```

因此页面信息层级必须围绕：

```text
Repository Context
        ↓
New Development Task
        ↓
Recent Runs
```

展开。

---

# 3. 当前页面主要问题

## 3.1 左侧仓库区域信息不足

当前左侧只有一个仓库卡片，下面存在较大空白。

问题：

- 左栏存在感较弱
- 空间利用率低
- 不像真正的 Repository Navigation
- 如果只有单仓库，独立侧栏显得冗余

### 优化原则

如果未来支持多仓库：

```text
左栏保留
→ 升级为 Repository Sidebar
```

如果系统只操作单仓库：

```text
取消左栏
→ 仓库信息放入任务创建区顶部
```

MVP 推荐保留左栏，但让它真正承担“仓库导航”职责。

---

## 3.2 “发起开发需求”区域视觉权重不足

这是整个页面最重要的交互区域。

当前它和下面“运行历史”的视觉权重接近。

应强化为页面第一操作焦点：

```text
Select Repository
      ↓
Describe Task
      ↓
Choose Execution Mode
      ↓
Run
```

---

## 3.3 交互模式解释不够清楚

当前：

```text
逐步确认（推荐）
自动
```

用户不一定理解区别。

应明确说明：

### 逐步确认

```text
关键文件修改、提交、危险操作等阶段暂停，
等待用户确认后继续。
```

### 自动执行

```text
Agent 在授权范围内自动完成任务，
仅在异常或高风险操作时暂停。
```

---

## 3.4 运行历史过于“数据库表”

当前 Run ID 是最主要的信息。

但用户通常记得的是：

```text
“修复登录错误那次任务”
“增加搜索功能那次任务”
```

而不是：

```text
#edc6c4d2
```

因此历史列表应以：

```text
Task / Requirement
```

作为第一信息。

Run ID 降级为 metadata。

---

# 4. 推荐页面结构

```text
┌─────────────────────────────────────────────────────────────┐
│ 项目工作台                                  🌙  注册仓库     │
│ 管理代码仓库并向 AI 开发 Agent 发起任务                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Repository            New Development Task                  │
│ ┌──────────────┐      ┌──────────────────────────────────┐  │
│ │ noteapp      │      │ 你想让 Agent 完成什么？          │  │
│ │ main / HEAD  │      │                                  │  │
│ │ #dee34375    │      │ [ textarea.................... ] │  │
│ │              │      │                                  │  │
│ │ 最近运行 12 │      │ Execution Mode                   │  │
│ │ 成功率 83%  │      │ [逐步确认] [自动执行]            │  │
│ └──────────────┘      │                     [发起任务]   │  │
│                       └──────────────────────────────────┘  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ 最近运行                                              查看全部 │
│                                                             │
│ Task                   Status        Time        Run ID      │
│ 添加依赖说明文件        ✓ Completed   02:13      #edc6c4d2  │
│ 修复删除笔记异常        ✓ Completed   01:56      #ad9ca8fb  │
│ 增加搜索功能            ● Approval    昨天       #48f77a27  │
│ 优化 README             ○ Cancelled   昨天       #aa8005a7  │
└─────────────────────────────────────────────────────────────┘
```

---

# 5. 页面布局

## 5.1 主容器

推荐：

```text
max-width: 1200px ~ 1280px
margin: 0 auto
padding-inline: 24px ~ 32px
```

避免页面主体过窄导致左右区域显得空。

## 5.2 上半部分布局

推荐：

```text
Repository Sidebar:
280px ~ 320px

Task Creation Area:
flex: 1
```

两栏间距：

```text
24px
```

---

# 6. Repository Sidebar

## 6.1 如果支持多个仓库

结构：

```text
Repositories

[ Search repository... ]

● noteapp
  main · #dee34375

○ backend-api
  develop · #7ca18fd

○ web-console
  main · #51abc90
```

选中仓库使用：

```text
subtle blue/gray background
1px accent border
```

不要使用大阴影。

## 6.2 仓库卡片信息

建议显示：

```text
Repository Name
Branch
Short Commit SHA
Last Run
Run Count
Optional Success Rate
```

示例：

```text
noteapp
main · HEAD
#dee34375

Last run: 18 min ago
12 runs · 83% success
```

## 6.3 注册仓库

“注册仓库”是次级操作。

建议保留在页面右上角：

```text
+ 注册仓库
```

不要与“发起运行”竞争主视觉。

---

# 7. New Development Task

这是页面最重要区域。

标题建议：

```text
New Development Task
```

或中文：

```text
发起开发任务
```

副标题：

```text
用自然语言描述你希望 Agent 在当前仓库完成的工作
```

## 7.1 输入框

Textarea 应是主视觉元素。

推荐高度：

```text
120px ~ 160px
```

Placeholder 示例：

```text
例如：
为 NoteStore 增加搜索功能；
修复 delete(index) 越界时抛出 IndexError 的问题；
为现有登录流程补充 JWT 过期校验。
```

不要放过长说明文字在 textarea 周围。

---

# 8. Execution Mode

推荐使用：

```text
Segmented Control
```

示例：

```text
执行模式

[ ✓ 逐步确认 ] [ 自动执行 ]
```

下面显示当前模式说明：

```text
逐步确认：
Agent 会在关键代码修改、提交和危险操作前等待你的确认。
```

切到自动执行时：

```text
自动执行：
Agent 会在授权范围内持续推进，异常或高风险操作时才暂停。
```

---

# 9. 主按钮

页面唯一最强 CTA：

```text
▶ 发起任务
```

按钮状态：

```text
Disabled:
未输入需求

Enabled:
已有有效需求

Loading:
正在创建 Run...
```

不要让其他按钮使用相同视觉强度。

---

# 10. Recent Runs

运行历史从“数据库记录”改为“任务历史”。

推荐字段：

```text
Task
Status
Created Time
Duration
Run ID
```

可选增加：

```text
Cost
Agent Mode
```

## 10.1 第一列必须是任务描述

不要：

```text
#edc6c4d2
```

作为最重要内容。

推荐：

```text
添加依赖说明文件
#edc6c4d2
```

Run ID 放在任务标题下方作为 metadata。

## 10.2 Status

统一状态：

```text
Green:
Completed

Blue:
Running

Amber:
Human Approval / Waiting

Red:
Failed

Gray:
Cancelled
```

不要同时使用太多颜色。

## 10.3 行交互

整个 Run Row 可以点击：

```text
click
→ /runs/:runId
```

Hover 时仅使用：

```text
background change
```

避免按钮过多。

---

# 11. 历史列表密度

当前历史区域高度偏大。

推荐：

```text
默认显示最近 6~8 条
```

超过后：

```text
View all runs
```

或分页。

避免首页长期出现内部滚动条。

---

# 12. Header

推荐：

```text
项目工作台
管理代码仓库并发起 AI 软件开发任务
```

右侧：

```text
Theme
+ 注册仓库
```

避免放置运行态操作。

运行相关按钮：

```text
Stop
Diff
Artifacts
Metrics
```

应仅出现在 `Run Workspace`。

---

# 13. Typography

建议：

```text
Page Title:
20~24px / 600

Page Subtitle:
13~14px / 400

Section Title:
14~16px / 600

Primary Text:
13~14px / 400~500

Metadata:
11~12px / 400

Run ID / SHA:
12px monospace
```

当前页面部分文字偏小、偏灰。

需要提高：

```text
Primary text contrast
```

但 metadata 可以保持弱化。

---

# 14. Spacing

统一使用：

```text
4px / 8px system
```

推荐：

```text
Page section gap: 24~32px
Card padding: 20~24px
Form element gap: 12~16px
Table row vertical padding: 12~14px
```

避免不规则：

```text
13px / 19px / 27px
```

---

# 15. Border / Radius / Shadow

## Border

```text
1px solid neutral border
```

优先用 spacing 建立层级。

## Radius

统一：

```text
8px
```

按钮可：

```text
6px
```

## Shadow

默认：

```text
none
```

仅 Modal / Dropdown / Floating Panel 使用轻微 shadow。

---

# 16. Color System

推荐语义：

```text
Primary:
deep neutral / navy

Success:
green

Running / Info:
blue

Warning / Approval:
amber

Error:
red

Cancelled / Disabled:
gray
```

不要：

```text
为不同 Agent / Run 类型随机使用颜色
```

---

# 17. 页面视觉风格

目标：

```text
Developer Tool
AI Engineering Workspace
Minimal
Professional
Calm
Readable
```

避免：

```text
Marketing Landing Page
Heavy Gradient
Glassmorphism
Huge Rounded Cards
Decorative Shadow
Generic Purple AI UI
```

---

# 18. 响应式

## Desktop >= 1200px

```text
Repository | New Task
Recent Runs
```

## Tablet 768~1199px

上半部分：

```text
Repository
↓
New Task
```

改为上下布局。

## Mobile

页面结构：

```text
Header
Repository Selector
New Task
Recent Runs
```

仓库侧栏改成：

```text
Select / Drawer
```

---

# 19. 页面与 Run Workspace 的边界

本页面不要展示：

```text
Task DAG
Agent Timeline
Agent Logs
Human Approval Detail
Tool Calls
Validation Timeline
Reviewer Timeline
```

这些属于：

```text
/runs/:runId
```

本页面只展示 Run 的摘要状态。

---

# 20. 推荐路由

```text
/projects
```

项目列表。

```text
/projects/:projectId
```

当前 Project Workspace。

```text
/runs/:runId
```

Run Workspace。

---

# 21. AI 修改流程

AI 在修改现有页面时必须按以下顺序：

## Phase 1 — Audit

先检查：

```text
Page Layout
Repository Component
Task Form
Mode Switch
Run History
Typography
Spacing
```

输出需要修改的组件。

不要立即重写整个页面。

## Phase 2 — Layout

优先修改：

```text
1. Main Container
2. Repository Sidebar
3. New Development Task
4. Recent Runs
```

## Phase 3 — Visual Hierarchy

优化：

```text
Typography
Spacing
Color
Borders
Status
CTA
```

## Phase 4 — Interaction

检查：

```text
Repository selection
Mode switch
Run button
Run row navigation
```

## Phase 5 — Responsive

检查：

```text
1440px
1280px
1024px
768px
```

## Phase 6 — Visual Review

修改完成后重新渲染并检查：

- 页面是否仍然存在大片无意义空白
- New Development Task 是否成为第一操作焦点
- 左栏是否承担明确功能
- Recent Runs 是否易于扫描
- Run ID 是否被正确弱化
- 状态颜色是否统一
- 页面是否出现内部不必要滚动条
- Typography 是否过小
- CTA 是否足够明显
- 是否误加入 Run Workspace 的执行细节

发现问题后继续调整。

---

# 22. 验收标准

- [ ] 用户进入页面后能立即识别当前仓库
- [ ] 用户能在 3 秒内找到任务输入区域
- [ ] “发起任务”是页面唯一主要 CTA
- [ ] 逐步确认 / 自动执行的区别清晰
- [ ] Repository Sidebar 不再出现大面积无功能空白
- [ ] Run History 第一信息是任务内容而非 Run ID
- [ ] Run Status 颜色语义统一
- [ ] 首页不展示底层 Agent 执行细节
- [ ] 最近运行默认显示 6~8 条
- [ ] 页面不依赖大量 Card 和 Shadow
- [ ] 1440px 和 1280px 下空间利用合理
- [ ] 1024px 下可正常操作
- [ ] 不修改 Agent 业务流程
- [ ] 不修改 API
- [ ] 不修改 Run 状态逻辑
- [ ] 不修改 SSE 协议

---

# 23. 最终目标

本页面最终应表达：

```text
这是一个“项目任务入口”
而不是“Agent 运行监控台”
```

用户体验主线：

```text
选择仓库
   ↓
描述需求
   ↓
选择执行模式
   ↓
发起 Run
   ↓
查看历史
   ↓
进入 Run Workspace
```

所有视觉和交互设计都应服务于这条主线。
