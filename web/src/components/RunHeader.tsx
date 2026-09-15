/** 运行页 Header：左侧 = 返回 / 项目 / 运行状态 / 当前阶段；右侧 = Run ID / 费用·Token / 打断 / 审批模式 / 终止 / 更多。
 * 低频操作（Diff、产出物、留痕、指标、刷新、主题）收进「更多」菜单。
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type { RunInfo } from '../api/types'
import { fmtCost, fmtTokens, shortId } from '../lib/format'
import { toggleTheme, useThemeMode } from '../lib/theme'
import { AgentBadge, StatusBadge } from './badges'

const MODE_LABELS: Record<string, string> = {
  auto: '智能判定',
  query: '只读问答',
  develop: '开发任务',
}

interface MenuItem {
  label: string
  onClick: () => void
  checked?: boolean
}

function MoreMenu({ items }: { items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="更多操作"
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition-colors ${
          open
            ? 'border-slate-600 bg-slate-800 text-slate-100'
            : 'border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
        }`}
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="1.6" />
          <circle cx="12" cy="12" r="1.6" />
          <circle cx="19" cy="12" r="1.6" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-50 w-48 rounded-lg border border-slate-800 bg-slate-900 py-1 shadow-xl"
        >
          {items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              onClick={() => {
                setOpen(false)
                it.onClick()
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-slate-300 transition-colors hover:bg-slate-800/70"
            >
              <span className={`w-3 shrink-0 text-[10px] ${it.checked ? 'text-blue-400' : 'text-transparent'}`}>✓</span>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

interface RunHeaderProps {
  run: RunInfo | null
  runId: string
  active: boolean
  canPause: boolean
  isPaused: boolean
  pauseBusy: boolean
  pauseAsked: boolean
  onPause: () => void
  cancelBusy: boolean
  onCancel: () => void
  modeBusy: boolean
  onToggleMode: () => void
  showDiff: boolean
  onToggleDiff: () => void
  showMetrics: boolean
  onToggleMetrics: () => void
  onOpenArtifacts: () => void
  onOpenHistory: () => void
  onRefresh: () => void
  artifactCount: number
  /** 非空时显示「交流」抽屉开关（medium 布局） */
  chatToggleLabel: string | null
  chatOpen: boolean
  onToggleChat: () => void
}

export function RunHeader({
  run,
  runId,
  active,
  canPause,
  isPaused,
  pauseBusy,
  pauseAsked,
  onPause,
  cancelBusy,
  onCancel,
  modeBusy,
  onToggleMode,
  showDiff,
  onToggleDiff,
  showMetrics,
  onToggleMetrics,
  onOpenArtifacts,
  onOpenHistory,
  onRefresh,
  artifactCount,
  chatToggleLabel,
  chatOpen,
  onToggleChat,
}: RunHeaderProps) {
  const approvalMode = run?.approval_mode ?? 'auto'
  const interactive = approvalMode === 'interactive'
  const metrics = run?.metrics ?? {}
  const dark = useThemeMode() === 'dark'
  const [copied, setCopied] = useState(false)

  const copyRunId = async () => {
    try {
      await navigator.clipboard.writeText(runId)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // 剪贴板不可用时静默忽略
    }
  }

  const tokens =
    (typeof metrics.input_tokens === 'number' ? metrics.input_tokens : 0) +
    (typeof metrics.output_tokens === 'number' ? metrics.output_tokens : 0)

  const menuItems: MenuItem[] = [
    { label: '代码 Diff', checked: showDiff, onClick: onToggleDiff },
    { label: `产出物${artifactCount > 0 ? `（${artifactCount}）` : ''}`, onClick: onOpenArtifacts },
    { label: '审批留痕', onClick: onOpenHistory },
    { label: '运行指标', checked: showMetrics, onClick: onToggleMetrics },
    { label: '刷新数据', onClick: onRefresh },
    { label: copied ? '已复制 Run ID' : '复制 Run ID', onClick: () => void copyRunId() },
    { label: dark ? '切换为亮色主题' : '切换为暗色主题', onClick: toggleTheme },
  ]

  const segBtn = (on: boolean) =>
    `rounded px-2 py-1 text-[11px] transition-colors disabled:opacity-60 ${
      on ? 'bg-slate-700 text-slate-100' : 'text-slate-500 hover:text-slate-300'
    }`

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-800 px-3">
      {/* 左：返回 / 项目 / 状态 / 当前阶段 */}
      <Link
        to="/"
        title="返回项目列表"
        className="flex h-8 shrink-0 items-center whitespace-nowrap rounded-md px-2 text-xs text-slate-400 transition-colors hover:bg-slate-800/60 hover:text-slate-200"
      >
        ← 项目
      </Link>
      <div className="min-w-0">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="max-w-[220px] shrink-0 truncate text-[14px] font-semibold text-slate-100">
            {run?.project?.name ?? '运行详情'}
          </span>
          <StatusBadge status={run?.status ?? 'pending'} size="sm" />
          {run?.mode && (
            <span className="hidden shrink-0 whitespace-nowrap text-[11px] text-slate-500 min-[1000px]:inline">
              {MODE_LABELS[run.mode] ?? run.mode}
            </span>
          )}
          {run?.current_agent && <AgentBadge agent={run.current_agent} />}
        </div>
        <div className="mt-0.5 max-w-[38vw] truncate text-[11px] text-slate-500" title={run?.request}>
          {run ? run.request : '加载中…'}
        </div>
      </div>

      {/* 右：核心操作 */}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <button
          onClick={() => void copyRunId()}
          title="复制 Run ID"
          className="hidden whitespace-nowrap rounded px-1 font-mono text-[10px] text-slate-600 transition-colors hover:text-slate-400 xl:inline"
        >
          #{shortId(runId)}
        </button>
        <div className="hidden items-center gap-3 whitespace-nowrap font-mono text-[10px] text-slate-400 min-[1100px]:flex">
          <span title="累计费用">{fmtCost(typeof metrics.cost_usd === 'number' ? metrics.cost_usd : 0)}</span>
          <span title="累计 Token">{fmtTokens(tokens)} tok</span>
        </div>

        {canPause && (
          <button
            onClick={() => void onPause()}
            disabled={pauseBusy || pauseAsked}
            title="在下一个安全点暂停运行，暂停后可补充需求再继续"
            className="whitespace-nowrap rounded-md border border-slate-800 px-2.5 py-1.5 text-xs text-slate-400 transition-colors hover:border-slate-700 hover:text-slate-200 disabled:opacity-50"
          >
            {pauseAsked ? '等待安全点…' : pauseBusy ? '请求中…' : '打断'}
          </button>
        )}
        {isPaused && (
          <span className="whitespace-nowrap rounded-md border border-amber-800 bg-amber-950/40 px-2.5 py-1.5 text-xs text-amber-300">
            已暂停 · 见下方面板
          </span>
        )}

        {run && active && (
          <div className="flex shrink-0 items-center rounded-md border border-slate-800 p-0.5" title="审批模式">
            <button
              onClick={interactive ? onToggleMode : undefined}
              disabled={modeBusy}
              title="自动模式：仅高风险操作需要审批"
              className={segBtn(!interactive)}
            >
              自动
            </button>
            <button
              onClick={interactive ? undefined : onToggleMode}
              disabled={modeBusy}
              title="逐步确认：写文件 / 执行命令前暂停等你点击同意"
              className={segBtn(interactive)}
            >
              逐步确认
            </button>
          </div>
        )}

        {chatToggleLabel && (
          <button
            onClick={onToggleChat}
            title="打开 / 收起 AI 解说与交流"
            className={`whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
              chatOpen
                ? 'border-slate-600 bg-slate-800 text-slate-100'
                : 'border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
            }`}
          >
            {chatToggleLabel}
          </button>
        )}

        {active && (
          <button
            onClick={() => void onCancel()}
            disabled={cancelBusy}
            title="终止该运行（不提交，已产生的变更保留在工作区）"
            className="whitespace-nowrap rounded-md border border-rose-900/70 px-2.5 py-1.5 text-xs text-rose-300/90 transition-colors hover:border-rose-700 hover:text-rose-200 disabled:opacity-50"
          >
            {cancelBusy ? '终止中…' : '终止'}
          </button>
        )}

        <MoreMenu items={menuItems} />
      </div>
    </header>
  )
}
