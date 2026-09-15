/** Task 详情抽屉：任务描述、验收标准、执行结果与错误（点击 DAG 节点从右侧滑出）。 */
import { useEffect } from 'react'

import type { TaskItem } from '../api/types'
import { AgentBadge, TaskStatusBadge } from './badges'

const PRIORITY_CLS: Record<string, string> = {
  high: 'bg-rose-950/80 text-rose-300',
  medium: 'bg-amber-950/80 text-amber-300',
  low: 'bg-slate-800 text-slate-400',
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500">{label}</span>
      {children}
    </div>
  )
}

export function TaskDetail({ task, onClose }: { task: TaskItem | null; onClose: () => void }) {
  useEffect(() => {
    if (!task) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [task, onClose])

  if (!task) return null

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/35" onClick={onClose} />
      <aside className="slide-in-right fixed bottom-0 right-0 top-14 z-40 flex w-[420px] max-w-[92vw] flex-col border-l border-slate-800 bg-slate-900 shadow-xl">
        {/* 头部 */}
        <div className="flex shrink-0 items-start gap-3 border-b border-slate-800/60 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] font-semibold text-slate-400">{task.id}</span>
              <TaskStatusBadge status={task.status} />
              {task.assigned_agent && <AgentBadge agent={task.assigned_agent} />}
            </div>
            <div className="mt-1 text-[14px] font-semibold leading-snug text-slate-100">{task.title}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-xs text-slate-500 transition-colors hover:bg-slate-800/60 hover:text-slate-200"
          >
            关闭 ✕
          </button>
        </div>

        {/* 元信息 */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-slate-800/60 px-4 py-2">
          <MetaItem label="优先级">
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${PRIORITY_CLS[task.priority] ?? PRIORITY_CLS.low}`}
            >
              {task.priority || '—'}
            </span>
          </MetaItem>
          <MetaItem label="尝试">
            <span className="font-mono text-[11px] text-slate-300">{task.attempts} 次</span>
          </MetaItem>
          <MetaItem label="依赖">
            {task.dependencies.length ? (
              <span className="flex flex-wrap items-center gap-1">
                {task.dependencies.map((d) => (
                  <span key={d} className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                    {d}
                  </span>
                ))}
              </span>
            ) : (
              <span className="text-[11px] text-slate-500">无</span>
            )}
          </MetaItem>
        </div>

        {/* 内容 */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <section className="border-b border-slate-800/60 px-4 py-3">
            <h4 className="mb-1.5 text-[12px] font-semibold text-slate-400">任务描述</h4>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-300">
              {task.description || '（无描述）'}
            </p>
          </section>

          {task.acceptance_criteria.length > 0 && (
            <section className="border-b border-slate-800/60 px-4 py-3">
              <h4 className="mb-1.5 text-[12px] font-semibold text-slate-400">
                验收标准 <span className="font-normal text-slate-600">({task.acceptance_criteria.length})</span>
              </h4>
              <ul className="space-y-1.5">
                {task.acceptance_criteria.map((ac, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-slate-400">
                    <span className="mt-0.5 shrink-0 text-emerald-400">✓</span>
                    <span className="min-w-0 flex-1">{ac}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {task.result_summary && (
            <section className="border-b border-slate-800/60 px-4 py-3">
              <h4 className="mb-1.5 text-[12px] font-semibold text-slate-400">执行结果</h4>
              <p className="border-l-2 border-emerald-800/60 pl-2.5 whitespace-pre-line text-xs leading-relaxed text-slate-300">
                {task.result_summary}
              </p>
            </section>
          )}

          {task.error && (
            <section className="px-4 py-3">
              <h4 className="mb-1.5 text-[12px] font-semibold text-slate-400">错误信息</h4>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap border-l-2 border-rose-800/70 pl-2.5 font-mono text-[11px] leading-relaxed text-rose-300/90">
                {task.error}
              </pre>
            </section>
          )}
        </div>
      </aside>
    </>
  )
}
