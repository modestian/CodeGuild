/** 事件流 → 自然语言叙述（中文模板）。
 * 把后端的结构化事件翻译成"Agent 做了什么"的人话，供 AI 解说面板展示。
 * 返回 null 表示该事件不在叙述流中展示（避免刷屏）。
 */
import type { RunEvent } from '../api/types'

export interface Narrative {
  id: string
  seq: number
  ts: number
  kind: 'milestone' | 'task' | 'evidence' | 'interaction' | 'problem'
  title: string
  detail?: string
  agent: string
  /** true 时渲染为用户消息气泡（右侧，来自人工输入） */
  fromUser?: boolean
  /** true 表示运行最终结果（回答 / 结束总结）：完整展示不截断 */
  final?: boolean
}

const AGENT_NAMES: Record<string, string> = {
  supervisor: '调度中枢',
  product: '产品经理',
  architect: '架构师',
  coder: '开发工程师',
  tester: '测试工程师',
  reviewer: '代码审查员',
  researcher: '调研员',
  analyst: '项目分析员',
  intent_router: '意图路由',
  final_review: '终审',
  human: '你（人工）',
  human_approval: '人工审批',
  task_scheduler: '任务调度',
  repair: '修复',
  commit: '提交',
  system: '系统',
}

export const agentDisplayName = (agent: string) => AGENT_NAMES[agent] ?? (agent || '系统')

function str(v: unknown, max = 200): string {
  if (v === null || v === undefined) return ''
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function sourceSummary(data: Record<string, unknown>): string {
  const path = str(data.path || data.file || '')
  if (path) return path
  const cmd = str(data.command || data.cmd || '')
  if (cmd) return cmd
  return str(data.args || data.arguments || data.input || '', 120)
}

/** answer_ready 事件 → 完整回答正文（markdown + 要点 + 参考文件）。 */
function answerDetail(d: Record<string, unknown>): string {
  const raw = d.answer
  const answer: Record<string, unknown> = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const markdown =
    typeof answer.markdown === 'string' ? answer.markdown : typeof d.markdown === 'string' ? d.markdown : ''
  const keyPoints = Array.isArray(answer.key_points) ? answer.key_points.map(String).filter(Boolean) : []
  const files = Array.isArray(answer.files_referenced) ? answer.files_referenced.map(String).filter(Boolean) : []
  const parts: string[] = []
  if (markdown.trim()) parts.push(markdown.trim())
  if (keyPoints.length) parts.push(`要点速览\n${keyPoints.map((k) => `· ${k}`).join('\n')}`)
  if (files.length) parts.push(`参考文件：${files.join('、')}`)
  return parts.join('\n\n')
}

/** 单个事件 → 叙述条目；null 表示跳过。 */
export function narrate(ev: RunEvent): Narrative | null {
  const d = ev.data ?? {}
  const agent = ev.agent || 'system'
  const base = { id: ev.id, seq: ev.seq, ts: ev.ts, agent }

  switch (ev.type) {
    case 'run_started':
      return { ...base, kind: 'milestone', title: '运行已启动', detail: str(d.request || ev.message, 300) }
    case 'intent_decided': {
      const isQuery = d.intent === 'query'
      return {
        ...base,
        kind: 'milestone',
        title: isQuery ? '判定为「只读问答」：不会修改代码' : '判定为「开发任务」：进入开发闭环',
        detail: str(d.reason),
      }
    }
    case 'supervisor_analyzing':
      return { ...base, kind: 'milestone', title: '调度中枢正在分析当前进展…' }
    case 'supervisor_decision': {
      const next = str(d.next || d.action || d.decision)
      return { ...base, kind: 'milestone', title: `调度决策：下一步 → ${next || '继续推进'}`, detail: str(d.reason || ev.message) }
    }
    case 'requirements_ready':
      return { ...base, kind: 'milestone', title: '产品需求文档已完成', detail: str(d.summary || ev.message) }
    case 'architecture_ready':
      return { ...base, kind: 'milestone', title: '技术方案设计已完成', detail: str(d.summary || ev.message) }
    case 'tasks_generated': {
      const n = Number(d.count ?? (Array.isArray(d.tasks) ? d.tasks.length : 0))
      return { ...base, kind: 'milestone', title: `任务计划已生成${n ? `（共 ${n} 个任务）` : ''}`, detail: ev.message }
    }
    case 'answer_ready':
      return {
        ...base,
        kind: 'milestone',
        title: '已回答你的问题（只读问答，未改动代码）',
        detail: answerDetail(d) || str(ev.message),
        final: true,
      }
    case 'task_ready':
      return { ...base, kind: 'task', title: `任务就绪：${str(d.title || d.task || ev.message)}` }
    case 'task_started':
      return { ...base, kind: 'task', title: `开始任务：${str(d.title || d.task || ev.message)}`, detail: str(d.description) }
    case 'task_completed':
      return { ...base, kind: 'task', title: `完成任务：${str(d.title || d.task || ev.message)}`, detail: str(d.result || d.summary) }
    case 'task_failed':
      return { ...base, kind: 'problem', title: `任务失败：${str(d.title || d.task || ev.message)}`, detail: str(d.error || d.reason) }
    case 'agent_started':
      return { ...base, kind: 'task', title: `${agentDisplayName(agent)}开始工作`, detail: str(d.task || d.brief) }
    case 'agent_finished':
      return { ...base, kind: 'evidence', title: `${agentDisplayName(agent)}完成了本轮工作`, detail: str(d.summary || d.notes) }
    case 'plan_updated':
      return { ...base, kind: 'evidence', title: `${agentDisplayName(agent)}更新了工作计划`, detail: str(d.plan || d.summary) }
    case 'tool_call':
      return {
        ...base,
        kind: 'evidence',
        title: `${agentDisplayName(agent)}调用工具 ${str(d.tool || d.name || ev.message)}`,
        detail: sourceSummary(d),
      }
    case 'tool_result': {
      const ok = d.ok !== false && !d.error
      return {
        ...base,
        kind: ok ? 'evidence' : 'problem',
        title: `${str(d.tool || d.name || '工具')} 执行${ok ? '完成' : '出错'}`,
        detail: str(d.error || d.result || d.output, 160),
      }
    }
    case 'test_started':
      return { ...base, kind: 'evidence', title: '开始运行测试', detail: str(d.command) }
    case 'test_result': {
      const passed = d.passed === true
      const failures = Array.isArray(d.failures) ? d.failures.length : 0
      return {
        ...base,
        kind: passed ? 'evidence' : 'problem',
        title: passed ? '测试全部通过' : `测试未通过${failures ? `（${failures} 个失败）` : ''}`,
        detail: str(d.summary || d.reason || ev.message),
      }
    }
    case 'validation_result': {
      // 后端未在 data 中携带 passed，通过与否编码在 message 前缀（Validation passed / not passed）
      const passed = d.passed === true || /validation passed/i.test(ev.message || '')
      return {
        ...base,
        kind: passed ? 'evidence' : 'problem',
        title: passed ? '校验通过' : '校验未通过',
        detail: str(d.reason || d.summary || ev.message),
      }
    }
    case 'repairing':
      return { ...base, kind: 'interaction', title: '发现问题，进入修复循环', detail: str(d.reason || ev.message) }
    case 'review_started':
      return { ...base, kind: 'evidence', title: '代码审查开始' }
    case 'review_result': {
      const approved = d.approved === true
      const issues = Array.isArray(d.issues) ? d.issues.length : 0
      return {
        ...base,
        kind: approved ? 'evidence' : 'problem',
        title: approved ? '审查通过，变更符合要求' : `审查发现问题${issues ? `（${issues} 个）` : ''}`,
        detail: str(d.summary || d.reason || ev.message),
      }
    }
    case 'diff_ready':
      return { ...base, kind: 'evidence', title: '代码变更已生成，可在右上角查看 Diff' }
    case 'approval_required':
      return { ...base, kind: 'interaction', title: '需要你的审批', detail: str(d.reason || ev.message) }
    case 'approval_received':
      return { ...base, kind: 'interaction', title: `已收到人工决定：${str(d.decision || ev.message)}`, detail: str(d.note) }
    case 'pause_requested':
      return { ...base, kind: 'interaction', title: '收到打断请求，将在安全点暂停', detail: str(d.reason) }
    case 'pause_resumed':
      return { ...base, kind: 'interaction', title: '运行已恢复', detail: str(d.guidance || ev.message) }
    case 'guidance_received':
      return { ...base, kind: 'interaction', title: str(d.text || ev.message, 300), fromUser: true }
    case 'guidance_applied':
      return { ...base, kind: 'interaction', title: '补充需求已注入 Agent 上下文', detail: str(d.text || ev.message, 300) }
    case 'commit_done':
      return { ...base, kind: 'milestone', title: '变更已提交到隔离分支', detail: str(d.commit || d.branch || ev.message) }
    case 'run_finished': {
      const summary = typeof d.summary === 'string' && d.summary.trim() ? d.summary.trim() : str(ev.message)
      return { ...base, kind: 'milestone', title: '本次运行已完成', detail: summary, final: true }
    }
    case 'run_failed': {
      const summary = typeof d.summary === 'string' && d.summary.trim() ? d.summary.trim() : str(d.error || ev.message)
      return { ...base, kind: 'problem', title: '运行未能完成', detail: summary, final: true }
    }
    case 'run_cancelled':
      return { ...base, kind: 'problem', title: '运行已被取消', detail: str(ev.message) }
    case 'error':
      return { ...base, kind: 'problem', title: '发生错误', detail: str(d.error || ev.message) }
    case 'log':
      return null // 日志不进叙述流，避免刷屏
    default:
      return null
  }
}

export const narrateAll = (events: RunEvent[]): Narrative[] => {
  const out: Narrative[] = []
  let pendingApproval = -1 // 当前未决审批在 out 中的位置（-1 = 无）
  for (const ev of events) {
    const n = narrate(ev)
    if (!n) continue
    if (n.title === '需要你的审批') {
      // 同一审批请求会被 runtime 重放重复发射，并伴随载荷事件；
      // 从请求到人工决定之间合并为一条，优先采用携带载荷 reason 的详情
      if (pendingApproval >= 0) {
        const prev = out[pendingApproval]
        const nd = n.detail ?? ''
        const hasPayloadReason = typeof (ev.data as Record<string, unknown> | undefined)?.reason === 'string'
        if (nd && (hasPayloadReason || nd.length > (prev.detail?.length ?? 0))) {
          out[pendingApproval] = { ...prev, detail: nd }
        }
      } else {
        out.push(n)
        pendingApproval = out.length - 1
      }
      continue
    }
    // 同一决定会被 run_manager 与图节点先后各发一次（“continue” + “Human chose to continue…”）：合并为一条
    if (n.title.startsWith('已收到人工决定：')) {
      const prev = out[out.length - 1]
      if (prev && prev.title.startsWith('已收到人工决定：')) continue
    }
    // 过程类叙述（agent / tool）不打断未决审批窗口；其余叙述（人工决定、里程碑等）结束窗口
    if (n.kind !== 'task' && n.kind !== 'evidence') pendingApproval = -1
    out.push(n)
  }
  return out
}
