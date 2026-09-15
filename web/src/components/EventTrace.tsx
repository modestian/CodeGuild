/** Agent 执行轨迹：层级化时间线。
 * - 一级条目：阶段里程碑（任务/校验/测试/审查/重试/审批…），始终可见；
 * - 二级条目：过程事件（agent/tool/log…），默认折叠，可展开查看原始数据。
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import type { RunEvent } from '../api/types'
import { fmtTime } from '../lib/format'
import { narrate } from '../lib/narrative'
import { buildTimeline, type TimelineGroup, type TimelineKind } from '../lib/timeline'
import { EventTypeTag } from './badges'

const KIND_DOT: Record<TimelineKind, string> = {
  info: 'bg-blue-400',
  success: 'bg-emerald-400',
  error: 'bg-rose-400',
  warning: 'bg-amber-400',
  approval: 'bg-amber-400',
  neutral: 'bg-slate-500',
}

/** 仅关键事件使用强调背景（普通条目无卡片、无边框）。 */
const KIND_BOX: Record<TimelineKind, string> = {
  info: '',
  neutral: '',
  success: 'bg-emerald-950/20',
  warning: 'bg-amber-950/20',
  error: 'bg-rose-950/25',
  approval: 'border-l-2 border-amber-600/70 bg-amber-950/25',
}

const KIND_TITLE: Record<TimelineKind, string> = {
  info: 'text-slate-200',
  neutral: 'text-slate-300',
  success: 'text-emerald-200',
  warning: 'text-amber-200',
  error: 'text-rose-200',
  approval: 'font-semibold text-amber-100',
}

function DetailRow({ ev, open, onToggle }: { ev: RunEvent; open: boolean; onToggle: () => void }) {
  const n = narrate(ev)
  const hasData = !!ev.data && Object.keys(ev.data).length > 0
  return (
    <div className="rounded px-1.5 py-1 hover:bg-slate-800/30">
      <div
        className={`flex items-center gap-2 ${hasData ? 'cursor-pointer' : ''}`}
        onClick={hasData ? onToggle : undefined}
      >
        <span className="shrink-0 font-mono text-[10px] text-slate-600">{fmtTime(ev.ts)}</span>
        <EventTypeTag type={ev.type} />
        <span className="min-w-0 flex-1 truncate text-[11px] text-slate-400">
          {n?.title ?? ev.message ?? ev.type}
        </span>
        {hasData && <span className="shrink-0 text-[10px] text-slate-600">{open ? '▾' : '▸'}</span>}
      </div>
      {n?.detail && (
        <div className="mt-0.5 line-clamp-2 break-all pl-1 text-[11px] leading-4 text-slate-600">{n.detail}</div>
      )}
      {open && hasData && (
        <pre className="mt-1 max-h-48 overflow-auto rounded border border-slate-800 bg-slate-950/80 p-2 font-mono text-[10px] leading-relaxed text-slate-400">
          {JSON.stringify(ev.data, null, 2)}
        </pre>
      )}
    </div>
  )
}

function GroupRow({
  group,
  open,
  preview,
  openItems,
  onToggle,
  onToggleItem,
}: {
  group: TimelineGroup
  open: boolean
  preview: string | null
  openItems: Set<number>
  onToggle: () => void
  onToggleItem: (seq: number) => void
}) {
  const hasItems = group.items.length > 0
  return (
    <div className={`rounded-md ${KIND_BOX[group.kind]}`}>
      <button
        type="button"
        onClick={() => hasItems && onToggle()}
        className={`flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left ${
          hasItems ? 'cursor-pointer hover:bg-slate-800/30' : 'cursor-default'
        }`}
      >
        <span className={`mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full ${KIND_DOT[group.kind]}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className={`min-w-0 flex-1 truncate text-[13px] leading-5 ${KIND_TITLE[group.kind]}`}>
              {group.title}
            </span>
            {hasItems && (
              <span className="shrink-0 font-mono text-[10px] text-slate-600">
                {open ? '▾' : '▸'}
                {group.items.length}
              </span>
            )}
            <span className="shrink-0 font-mono text-[10px] text-slate-600">{fmtTime(group.ts)}</span>
          </span>
          {group.detail && !open && (
            <span className="mt-0.5 line-clamp-1 block text-[11px] leading-4 text-slate-500">{group.detail}</span>
          )}
          {preview && !open && (
            <span className="mt-0.5 line-clamp-1 block text-[11px] leading-4 text-slate-600">{preview}</span>
          )}
        </span>
      </button>

      {open && hasItems && (
        <div className="mb-1 ml-[10px] border-l border-slate-800/70 pl-2 pr-2">
          {group.items.map((ev) => (
            <DetailRow key={ev.seq} ev={ev} open={openItems.has(ev.seq)} onToggle={() => onToggleItem(ev.seq)} />
          ))}
        </div>
      )}
    </div>
  )
}

export function EventTrace({
  events,
  connected,
  ended = false,
}: {
  events: RunEvent[]
  connected: boolean
  ended?: boolean
}) {
  const groups = useMemo(() => buildTimeline(events), [events])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [expandAll, setExpandAll] = useState(false)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [openItems, setOpenItems] = useState<Set<number>>(new Set())

  const tail = groups.length ? `${groups.length}:${groups[groups.length - 1].items.length}` : '0'
  useEffect(() => {
    if (!autoScroll) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [tail, autoScroll, openGroups, expandAll])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(nearBottom)
  }

  const toggleGroup = (id: string) =>
    setOpenGroups((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleItem = (seq: number) =>
    setOpenItems((s) => {
      const next = new Set(s)
      if (next.has(seq)) next.delete(seq)
      else next.add(seq)
      return next
    })

  const anyOpen = expandAll || openGroups.size > 0
  const toggleExpandAll = () => {
    if (anyOpen) {
      setExpandAll(false)
      setOpenGroups(new Set())
    } else {
      setExpandAll(true)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2.5 overflow-hidden border-b border-slate-800/60 px-3 py-1.5 text-[11px] text-slate-500">
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              ended ? 'bg-slate-500' : connected ? 'bg-emerald-400' : 'bg-amber-400'
            }`}
          />
          {ended ? '事件流已结束' : connected ? 'SSE 已连接' : '连接中断，重试中…'}
        </span>
        <span className="hidden shrink-0 whitespace-nowrap tabular-nums min-[1100px]:inline">
          阶段 {groups.length} · 事件 {events.length}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <button
            onClick={toggleExpandAll}
            className="whitespace-nowrap text-slate-500 transition-colors hover:text-slate-300"
          >
            {anyOpen ? '折叠全部' : '展开全部'}
          </button>
          <label className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap select-none">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="h-3 w-3 accent-blue-500"
            />
            自动滚动
          </label>
        </div>
      </div>

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {groups.length === 0 && (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">等待事件…</div>
        )}
        <div className="space-y-0.5">
          {groups.map((g, i) => {
            const live = !ended && i === groups.length - 1 && g.items.length > 0
            const lastItem = live ? g.items[g.items.length - 1] : null
            const preview = lastItem ? (narrate(lastItem)?.title ?? lastItem.message ?? null) : null
            return (
              <div key={g.id} className="event-in">
                <GroupRow
                  group={g}
                  open={expandAll || openGroups.has(g.id)}
                  preview={preview}
                  openItems={openItems}
                  onToggle={() => toggleGroup(g.id)}
                  onToggleItem={toggleItem}
                />
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
