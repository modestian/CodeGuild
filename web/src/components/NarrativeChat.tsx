/** AI 解说 · 实时交流面板：
 * - 叙述流：把事件流翻译成"Agent 做了什么"的自然语言（消息流形态，普通条目无卡片，仅关键事件用容器）
 * - 交流输入：随时向 Agent 追加需求（下一步自动采纳），用户消息以气泡显示在右侧
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api/client'
import type { RunEvent } from '../api/types'
import { fmtTime } from '../lib/format'
import { agentDisplayName, narrateAll, type Narrative } from '../lib/narrative'

/** 普通条目无容器；里程碑用左侧色条锚定；等待人工 / 异常才使用强调容器。 */
const KIND_BOX: Record<Narrative['kind'], string> = {
  milestone: 'border-l-2 border-blue-700/50 bg-slate-900/30 rounded-l-none rounded-r-md',
  task: '',
  evidence: '',
  interaction: 'border-l-2 border-amber-700/50 bg-amber-950/10 rounded-l-none rounded-r-md',
  problem: 'border-l-2 border-rose-700/60 bg-rose-950/15 rounded-l-none rounded-r-md',
}

const KIND_TITLE: Record<Narrative['kind'], string> = {
  milestone: 'text-slate-100',
  task: 'text-slate-200',
  evidence: 'text-slate-300',
  interaction: 'text-amber-100',
  problem: 'text-rose-200',
}

/** 左侧语义圆点：里程碑=蓝，任务/证据=灰阶，交互=琥珀，异常=玫红 */
const KIND_DOT: Record<Narrative['kind'], string> = {
  milestone: 'bg-blue-400',
  task: 'bg-slate-500',
  evidence: 'bg-slate-600',
  interaction: 'bg-amber-400',
  problem: 'bg-rose-400',
}

export function NarrativeChat({
  runId,
  events,
  active,
}: {
  runId: string
  events: RunEvent[]
  active: boolean
}) {
  const narratives = useMemo(() => narrateAll(events), [events])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [okMsg, setOkMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!autoScroll) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [narratives.length, autoScroll])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  const send = async () => {
    const t = text.trim()
    if (!t || busy || !active) return
    setBusy(true)
    setError(null)
    setOkMsg(null)
    try {
      await api.sendGuidance(runId, t)
      setText('')
      setOkMsg('已发送，Agent 将在下一步采纳')
      window.setTimeout(() => setOkMsg(null), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {narratives.length === 0 && (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            Agent 还没有动作，解说将随事件实时生成…
          </div>
        )}
        {narratives.map((n) =>
          n.fromUser ? (
            <div key={n.id} className="flex justify-end">
              <div className="event-in max-w-[88%] rounded-lg rounded-br-sm bg-slate-800/90 px-2.5 py-1.5">
                <div className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-slate-100">
                  {n.title}
                </div>
                <div className="mt-0.5 text-right text-[10px] text-slate-500">{fmtTime(n.ts)} · 你的补充需求</div>
              </div>
            </div>
          ) : (
            <div
              key={n.id}
              className={`event-in px-2.5 py-1.5 ${
                n.final ? 'rounded-md border border-slate-800 bg-slate-900/60' : KIND_BOX[n.kind]
              }`}
            >
              <div className="flex items-start gap-2">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${KIND_DOT[n.kind]}`} />
                <div className="min-w-0 flex-1">
                  <div className={`text-[12px] font-medium leading-snug ${KIND_TITLE[n.kind]}`}>{n.title}</div>
                  {n.detail && (
                    <div
                      className={`mt-0.5 whitespace-pre-wrap break-words text-[11px] leading-relaxed ${
                        n.final ? 'text-slate-300' : 'line-clamp-3 text-slate-400'
                      }`}
                    >
                      {n.detail}
                    </div>
                  )}
                  <div className="mt-0.5 text-[10px] text-slate-600">
                    {fmtTime(n.ts)}
                    {n.agent && n.agent !== 'system' ? ` · ${agentDisplayName(n.agent)}` : ''}
                  </div>
                </div>
              </div>
            </div>
          ),
        )}
      </div>

      <div className="shrink-0 border-t border-slate-800/60 px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder={active ? '与 Agent 交流：随时补充需求，回车发送' : '运行已结束，无法追加需求'}
            disabled={!active || busy}
            className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500 disabled:opacity-50"
          />
          <button
            onClick={() => void send()}
            disabled={!active || busy || !text.trim()}
            className="shrink-0 whitespace-nowrap rounded-md bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:opacity-40"
          >
            {busy ? '发送中…' : '发送'}
          </button>
        </div>
        <div className="mt-1 flex items-center justify-between gap-2 text-[10px]">
          <span className={error ? 'text-rose-400' : okMsg ? 'text-emerald-400' : 'text-slate-600'}>
            {error ?? okMsg ?? (active ? '补充需求不打断执行，Agent 下一步自动采纳；如需立即改写方向请用「打断」' : '运行已结束')}
          </span>
          <label className="flex shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap text-slate-600 select-none">
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
    </div>
  )
}
