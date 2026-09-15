# AGENTS.md — 面向 AI 编码助手的项目指南

CodeGuild（基于 LangGraph 的多 Agent 软件开发系统，FastAPI + React）。用户用自然语言提需求 → 意图路由（只读问答 / 开发闭环）→ 多 Agent 协作（需求 / 架构 / 编码 / 测试 / 审查）→ 人工审批（打断 / 同意 / 拒绝 / 补充需求）→ 提交到隔离分支。

## 常用命令（Windows + PowerShell）

- 启动后端（同时托管前端构建产物，访问 http://127.0.0.1:8000）：
  `.venv\Scripts\codeguild.exe serve`（旧命令 `ma-dev` 仍兼容）
- 构建前端（PowerShell 必须用 `npm.cmd`，`npm` 会被执行策略拦截）：
  `cd web; npm.cmd run build`
- 后端测试：`.venv\Scripts\python.exe -m pytest tests/ -q`（basetemp=.pytest_tmp，自动清空重建）
- 重启后端：`serve` 无热重载，改后端代码或重新构建 dist 后必须重启进程才生效
- LLM 配置在 `.env`（当前使用 DeepSeek 真实 API；测试用 mock LLM 脚本，无需 Key）

## 架构速览

- `app/graph/main_graph.py`：主图（load_project → classify_intent → supervisor → product / architect / development → final_review → human_approval → commit）
- `app/graph/development_graph.py`：开发子图（任务调度 → coding 子图 → 测试 → 审查 → 修复循环，含重试上限与人工介入）
- `app/graph/safe_point.py`：HITL 打断安全点（Supervisor 入口 + 任务调度器），`interrupt()` 挂起 / 恢复
- `app/agents/`：各 Agent 实现与 prompts；`analyst.py` 负责意图分类与只读问答
- `app/harness/`：执行循环 / 权限 / 策略（含敏感路径强制审批）/ 审批 / 重试 / guidance
- `app/services/run_manager.py`：运行生命周期、审批提交（pause 恢复 / 取消 / 工具审批 / 交付审批）
- `web/src/`：React 前端。RunPage 为三栏布局（TaskDAG 纵向 | Agent 执行轨迹 | AI 解说·交流），Diff 为右上角抽屉，NarrativeChat 用 `lib/narrative.ts` 模板把事件翻译成中文叙述
- `tests/`：pytest（asyncio_mode=auto）+ mock LLM 脚本（示例仓库由测试夹具现场生成）

## 关键约定

1. HITL 语义：
   - 打断（pause）：安全点挂起，载荷 `options=["resume","reject"]`；resume 时 note 作为补充需求注入 guidance；reject = 取消运行（cancelled）
   - 所有挂起载荷（tool_approval / approval_required / pause）必须携带唯一 `approval_id`：前端据此复位审批面板，确保同一工具多次请求、多次打断时不刷新页面也能正常操作
   - 工具审批 decision：interactive 模式用 `approve_once` / `approve_always`；auto 模式裸 `approve`
2. Mock LLM 脚本格式（`app_ctx.set_llm_script`）：
   - single 模式（如 intent_router）：直接返回原始 schema JSON，如 `{"intent":"query","reason":"..."}`
   - agentic 模式：decision 协议，如 `{"decision":"final","output":{...}}` 或 `{"decision":"tool_call","tool":"read_file","arguments":{...}}`
3. LangGraph interrupt/replay：节点恢复时从头重跑；状态清理（如 `clear_pause`）必须放在 `interrupt()` 返回之后，保证重放幂等
4. 前端终态处理：运行到达终态后忽略缓存的 `pending_approval`（避免底部面板残留）；`waiting_approval` / `needs_human` 状态不显示"打断"按钮
5. 执行段预算（Session 复用）：`RuntimeSession` 的对话记忆（messages/plan/changed_files）跨执行段保留，预算计数器（steps/tokens/cost/tool_failures/started_ts）按执行段管理——上一段 finished/stopped/failed 后再次执行时由 `AgentRuntime._reset_execution_budget` 重置，避免 token 到顶 / 轮次上限后"继续迭代"在循环入口立即判停；审批恢复（awaiting_approval）属同一执行段仅刷新墙钟；循环内已挂起的工具调用优先于停止条件执行
6. PowerShell：命令分隔用 `;` 而非 `&&`
7. 仓库识别：判断“文件夹是否为 Git 仓库”必须锚定仓库根（`rev-parse --show-toplevel` 等于该路径）；`--is-inside-work-tree` 对嵌套子目录同样返回 true，曾导致 git 初始化/提交误落到外层仓库（含测试误提交整个项目）

## 文件清理约定（重要）

以下为临时 / 可再生产物，**可随时删除、无需提交**：

- `_serve*.log`、根目录 `_*.py` / `_*.txt`：本地调试脚本与运行日志
- `.pytest_tmp/`：pytest basetemp，每次测试自动清空重建
- `ee-*.png` 等验证截图：端到端验证的临时产物，验证完成后即可删除
- 根目录 `*-page.png` / `*-panel.png` 等演示截图：更新 UI 后可重新生成

需要保留：

- `data/`：运行时数据（copilot.db、checkpoints.sqlite、sessions/、workspaces/、artifacts/），勿删
- `docs/`：设计方案与需求报告书
- `web/dist/`：前端构建产物（可重新构建，但线上托管依赖它）
