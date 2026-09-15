/** 产出物查看器（全屏覆盖层）：需求 / 架构 / 测试 / 审查 / 最终报告 的结构化浏览。 */
import { useEffect, useState } from 'react'

import { useArtifact } from '../api/hooks'
import type { ArtifactMeta } from '../api/types'
import { fmtDateTime } from '../lib/format'
import { AgentBadge } from './badges'
import {
  ArchitectureView,
  FinalReportView,
  RequirementsView,
  ReviewReportView,
  TestReportView,
} from './ArtifactRenderers'

const RENDERERS: Record<string, (props: { data: Record<string, unknown> }) => React.ReactNode> = {
  requirements: RequirementsView,
  architecture: ArchitectureView,
  test_report: TestReportView,
  review_report: ReviewReportView,
  final_report: FinalReportView,
}

const fmtSize = (n: number): string => {
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

function SideItem({
  meta,
  selected,
  onClick,
}: {
  meta: ArtifactMeta
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={!meta.exists}
      className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
        selected
          ? 'border-blue-600/60 bg-blue-950/25'
          : meta.exists
            ? 'border-slate-800 bg-slate-900/50 hover:border-slate-700'
            : 'cursor-not-allowed border-slate-800/60 bg-slate-900/20 opacity-45'
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.exists ? 'bg-emerald-400' : 'bg-slate-600'}`}
        />
        <span className={`text-xs font-medium ${selected ? 'text-slate-100' : 'text-slate-300'}`}>{meta.title}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <AgentBadge agent={meta.agent} />
        <span className="font-mono text-[10px] text-slate-600">
          {meta.exists ? fmtSize(meta.size) : '未生成'}
        </span>
      </div>
    </button>
  )
}

export function ArtifactViewer({
  runId,
  metas,
  open,
  onClose,
}: {
  runId: string
  metas: ArtifactMeta[]
  open: boolean
  onClose: () => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [jsonView, setJsonView] = useState(false)

  // 打开时自动选中第一个已生成的产出物
  useEffect(() => {
    if (!open) return
    setSelected((prev) => {
      if (prev && metas.some((m) => m.name === prev && m.exists)) return prev
      return metas.find((m) => m.exists)?.name ?? null
    })
  }, [open, metas])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const { data: artifactData, error: artifactError } = useArtifact(runId, selected, open)

  if (!open) return null

  const activeMeta = metas.find((m) => m.name === selected) ?? null
  const Renderer = selected ? RENDERERS[selected] : undefined
  const data = artifactData?.name === selected ? artifactData.data : null

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/45 p-6"
      onClick={onClose}
    >
      <div
        className="slide-up flex h-full max-h-[820px] w-full max-w-[1180px] flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 顶部 */}
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-slate-800 px-4">
          <span className="text-sm font-semibold text-slate-100">产出物</span>
          <span className="text-[11px] text-slate-500">多 Agent 结构化交付链路：需求 → 架构 → 代码 → 测试 → 审查 → 汇总</span>
          <button
            onClick={onClose}
            className="ml-auto rounded-md border border-slate-800 px-2.5 py-1 text-xs text-slate-400 transition-colors hover:border-slate-700 hover:text-slate-200"
          >
            关闭 ✕
          </button>
        </div>

        <div className="flex min-h-0 flex-1">
          {/* 左侧：产出物列表 */}
          <aside className="flex w-60 shrink-0 flex-col gap-2 overflow-y-auto border-r border-slate-800/60 p-3">
            {metas.map((m) => (
              <SideItem key={m.name} meta={m} selected={m.name === selected} onClick={() => setSelected(m.name)} />
            ))}
            {metas.length === 0 && (
              <div className="p-4 text-center text-xs text-slate-600">加载中…</div>
            )}
          </aside>

          {/* 右侧：内容 */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-11 shrink-0 items-center gap-3 border-b border-slate-800/60 px-4">
              {activeMeta ? (
                <>
                  <span className="text-xs font-semibold text-slate-200">{activeMeta.title}</span>
                  <AgentBadge agent={activeMeta.agent} />
                  {activeMeta.modified_at && (
                    <span className="font-mono text-[10px] text-slate-600">
                      更新于 {fmtDateTime(activeMeta.modified_at)}（运行中自动刷新）
                    </span>
                  )}
                </>
              ) : (
                <span className="text-xs text-slate-500">选择左侧产出物查看</span>
              )}
              <div className="ml-auto flex items-center gap-1 rounded-md border border-slate-800 p-0.5">
                <button
                  onClick={() => setJsonView(false)}
                  className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                    !jsonView ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  结构化
                </button>
                <button
                  onClick={() => setJsonView(true)}
                  className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                    jsonView ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  JSON
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {artifactError && <div className="text-xs text-rose-400">加载失败：{artifactError}</div>}
              {!artifactError && !data && selected && (
                <div className="flex h-full items-center justify-center text-sm text-slate-500">加载产出物…</div>
              )}
              {!selected && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-slate-500">
                  <span>尚未生成任何产出物</span>
                  <span className="text-xs text-slate-600">各 Agent 完成阶段任务后，产出物将在此自动出现</span>
                </div>
              )}
              {data &&
                (jsonView || !Renderer ? (
                  <pre className="rounded-lg border border-slate-800 bg-slate-950/80 p-3 font-mono text-[10px] leading-relaxed text-slate-400">
                    {JSON.stringify(data, null, 2)}
                  </pre>
                ) : (
                  <Renderer data={data} />
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
