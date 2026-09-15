/** 事件流 → 层级化时间线（Agent 执行轨迹的展示模型）。
 * 纯函数转换：把平铺的 SSE 事件按「阶段里程碑」分组：
 * - 一级条目：里程碑事件（任务开始 / 校验 / 测试 / 审查 / 重试 / 人工审批…），始终可见；
 * - 二级条目：过程事件（agent / tool / log…），默认折叠，可展开查看原始数据。
 * 不改变事件语义与顺序，仅调整展示结构。
 */
import type { RunEvent } from '../api/types'
import { narrate } from './narrative'

export type TimelineKind = 'info' | 'success' | 'error' | 'warning' | 'approval' | 'neutral'

export interface TimelineGroup {
  id: string
  seq: number
  ts: number
  agent: string
  kind: TimelineKind
  title: string
  detail?: string
  /** 组内二级事件（默认折叠） */
  items: RunEvent[]
}

/** 一级事件 → 阶段类型；不在此表内的事件作为当前分组的二级详情。 */
const PRIMARY_KIND: Record<string, TimelineKind> = {
  run_started: 'info',
  intent_decided: 'info',
  supervisor_decision: 'info',
  requirements_ready: 'success',
  architecture_ready: 'success',
  tasks_generated: 'success',
  answer_ready: 'success',
  task_started: 'info',
  task_completed: 'success',
  task_failed: 'error',
  test_result: 'error',
  validation_result: 'warning',
  review_result: 'warning',
  repairing: 'warning',
  approval_required: 'approval',
  approval_received: 'approval',
  pause_requested: 'approval',
  pause_resumed: 'info',
  guidance_applied: 'info',
  commit_done: 'success',
  run_finished: 'success',
  run_failed: 'error',
  run_cancelled: 'error',
  error: 'error',
}

/** 依据事件数据对静态分类做动态修正（测试 / 校验 / 审查的通过与否）。 */
function kindOf(ev: RunEvent): TimelineKind | null {
  const base = PRIMARY_KIND[ev.type]
  if (!base) return null
  const d = ev.data ?? {}
  if (ev.type === 'test_result') return d.passed === true ? 'success' : 'error'
  // 校验通过伴随任务完成，信息重复：降为二级详情；仅未通过时作为里程碑警示
  if (ev.type === 'validation_result') {
    const passed = d.passed === true || /validation passed/i.test(ev.message ?? '')
    return passed ? null : 'warning'
  }
  if (ev.type === 'review_result') return d.approved === true ? 'success' : 'warning'
  return base
}

/** 审批类事件会在 runtime 重放与图层先后重复发射：相邻同类时合并为一个条目。 */
const MERGEABLE_TYPES = new Set(['approval_required', 'approval_received'])

/** 按事件到达顺序分组：里程碑开启新组，过程事件进入当前组的二级列表。 */
export function buildTimeline(events: RunEvent[]): TimelineGroup[] {
  const groups: TimelineGroup[] = []
  let current: TimelineGroup | null = null
  let openType: string | null = null // 当前组由哪个里程碑事件开启

  for (const ev of events) {
    const kind = kindOf(ev)
    if (kind) {
      // 同一审批请求 / 决定的重复事件（无载荷 + 载荷、run_manager + 图层）：合并为一体
      if (MERGEABLE_TYPES.has(ev.type) && current && openType === ev.type) {
        current.items.push(ev)
        if (ev.type === 'approval_required') {
          const n = narrate(ev)
          const nd = n?.detail || ''
          // 载荷事件（携带 data.reason）优先；否则仅在信息更长时升级
          const hasPayloadReason = typeof (ev.data as Record<string, unknown> | undefined)?.reason === 'string'
          if (nd && (hasPayloadReason || nd.length > (current.detail?.length ?? 0))) current.detail = nd
        }
        continue
      }
      const n = narrate(ev)
      current = {
        id: ev.id,
        seq: ev.seq,
        ts: ev.ts,
        agent: ev.agent,
        kind,
        title: n?.title ?? ev.message ?? ev.type,
        detail: n?.detail || undefined,
        items: [],
      }
      openType = ev.type
      groups.push(current)
    } else {
      if (!current) {
        // 里程碑出现前的过程事件（极少）：归入一个中性「准备中」分组
        current = {
          id: `lead-${ev.id}`,
          seq: ev.seq,
          ts: ev.ts,
          agent: ev.agent,
          kind: 'neutral',
          title: '运行准备中',
          items: [],
        }
        groups.push(current)
      }
      current.items.push(ev)
    }
  }
  return groups
}
