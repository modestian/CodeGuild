/** 状态 / Agent / 事件类型徽章（统一视觉语言：方角小标签 + 语义色，克制产品风）。 */

import { agentDisplayName } from '../lib/narrative'

const RUN_STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  pending: { label: '等待中', cls: 'bg-slate-800/80 text-slate-300 border-slate-700', dot: 'bg-slate-400' },
  running: { label: '执行中', cls: 'bg-blue-950/80 text-blue-300 border-blue-800', dot: 'bg-blue-400' },
  waiting_approval: { label: '待审批', cls: 'bg-amber-950/80 text-amber-300 border-amber-800', dot: 'bg-amber-400' },
  needs_human: { label: '需人工', cls: 'bg-amber-950/80 text-amber-300 border-amber-800', dot: 'bg-amber-400' },
  completed: { label: '已完成', cls: 'bg-emerald-950/80 text-emerald-300 border-emerald-800', dot: 'bg-emerald-400' },
  failed: { label: '失败', cls: 'bg-rose-950/80 text-rose-300 border-rose-800', dot: 'bg-rose-400' },
  rejected: { label: '已拒绝', cls: 'bg-rose-950/80 text-rose-300 border-rose-800', dot: 'bg-rose-400' },
  cancelled: { label: '已取消', cls: 'bg-slate-800/80 text-slate-400 border-slate-700', dot: 'bg-slate-500' },
}

export function StatusBadge({ status, size = 'md' }: { status: string; size?: 'sm' | 'md' }) {
  const s = RUN_STATUS[status] ?? RUN_STATUS.pending
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded border font-medium ${s.cls} ${
        size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

const TASK_STATUS: Record<
  string,
  { label: string; cls: string; border: string; text: string; dot: string; ring: string }
> = {
  PENDING: {
    label: '待处理',
    cls: 'bg-slate-800 text-slate-400',
    border: 'border-slate-700/80',
    text: 'text-slate-500',
    dot: 'bg-slate-600',
    ring: '',
  },
  READY: {
    label: '就绪',
    cls: 'bg-blue-950 text-blue-300',
    border: 'border-slate-700',
    text: 'text-blue-400',
    dot: 'bg-blue-400',
    ring: '',
  },
  RUNNING: {
    label: '执行中',
    cls: 'bg-blue-950 text-blue-300',
    border: 'border-blue-600/80',
    text: 'text-blue-300',
    dot: 'bg-blue-400',
    ring: 'ring-1 ring-blue-500/25',
  },
  BLOCKED: {
    label: '阻塞',
    cls: 'bg-amber-950 text-amber-300',
    border: 'border-amber-600/80',
    text: 'text-amber-300',
    dot: 'bg-amber-400',
    ring: '',
  },
  REVIEWING: {
    label: '审查中',
    cls: 'bg-blue-950 text-blue-300',
    border: 'border-blue-800/80',
    text: 'text-blue-300',
    dot: 'bg-blue-400',
    ring: '',
  },
  COMPLETED: {
    label: '完成',
    cls: 'bg-emerald-950 text-emerald-300',
    border: 'border-emerald-800/80',
    text: 'text-emerald-300',
    dot: 'bg-emerald-400',
    ring: '',
  },
  FAILED: {
    label: '失败',
    cls: 'bg-rose-950 text-rose-300',
    border: 'border-rose-700/80',
    text: 'text-rose-300',
    dot: 'bg-rose-400',
    ring: '',
  },
}

export function TaskStatusBadge({ status, size = 'sm' }: { status: string; size?: 'sm' | 'md' }) {
  const s = TASK_STATUS[status] ?? TASK_STATUS.PENDING
  return (
    <span className={`inline-flex shrink-0 whitespace-nowrap rounded font-medium ${s.cls} ${size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs'}`}>
      {s.label}
    </span>
  )
}

export function taskStatusMeta(status: string) {
  return TASK_STATUS[status] ?? TASK_STATUS.PENDING
}

/** Agent 标签：统一中性色 + 中文显示名（节点名也映射，不裸露英文状态码）。 */
const AGENT_BADGE_CLS = 'bg-slate-800/70 text-slate-300 border-slate-700'

export function AgentBadge({ agent }: { agent: string }) {
  return (
    <span className={`inline-flex min-w-16 shrink-0 justify-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] tracking-wide ${AGENT_BADGE_CLS}`}>
      {agentDisplayName(agent)}
    </span>
  )
}

const EVENT_TAG: Record<string, string> = {
  // 成功 / 完成（统一 emerald）
  task_completed: 'bg-emerald-950 text-emerald-300',
  test_result: 'bg-emerald-950 text-emerald-300',
  validation_result: 'bg-emerald-950 text-emerald-300',
  review_result: 'bg-emerald-950 text-emerald-300',
  commit_done: 'bg-emerald-950 text-emerald-300',
  run_finished: 'bg-emerald-950 text-emerald-300',
  // 失败 / 异常（统一 rose）
  task_failed: 'bg-rose-950 text-rose-300',
  run_failed: 'bg-rose-950 text-rose-300',
  run_cancelled: 'bg-rose-950 text-rose-300',
  error: 'bg-rose-950 text-rose-300',
  // 等待人工 / 修复中（统一 amber）
  approval_required: 'bg-amber-950 text-amber-300',
  repairing: 'bg-amber-950 text-amber-300',
  pause_requested: 'bg-amber-950 text-amber-300',
}

/** 其余过程类事件统一中性色（避免彩色标签刷屏）。 */

/** 审批模式徽章：interactive（逐步确认）/ auto（仅高风险）。 */
export function ApprovalModeBadge({ mode }: { mode: string }) {
  const interactive = mode === 'interactive'
  return (
    <span
      title={
        interactive
          ? '逐步确认：写文件、执行命令前暂停等待人工同意/拒绝'
          : '自动模式：仅高风险操作暂停等待人工审批'
      }
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10px] ${
        interactive
          ? 'border-blue-800/70 bg-blue-950/70 text-blue-300'
          : 'border-slate-700 bg-slate-800/70 text-slate-400'
      }`}
    >
      {interactive ? '逐步确认' : '自动'}
    </span>
  )
}

export function EventTypeTag({ type }: { type: string }) {
  const cls = EVENT_TAG[type] ?? 'bg-slate-800 text-slate-400'
  return (
    <span className={`inline-flex shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] leading-4 ${cls}`}>{type}</span>
  )
}
