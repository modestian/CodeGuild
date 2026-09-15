/** 人工审批 / 打断挂起面板（Contextual：仅在挂起时出现，紧凑单列，操作行在底部）。
 * - pause：用户打断后的挂起面板（继续运行 / 取消运行），备注作为补充需求注入
 * - tool_approval：关键操作逐次审批（同意一次 / 后续免问 / 拒绝），arguments 可展开
 * - needs_human：达到重试上限的人工介入（继续迭代 / 批准 / 拒绝），诊断可展开
 * - 默认：最终审批（批准并提交 / 拒绝）
 */
import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { ApprovalPayload } from '../api/types'

const DECISION_UI: Record<string, { label: string; cls: string; hint: string }> = {
  approve: {
    label: '批准并提交',
    cls: 'bg-primary text-primary-fg hover:bg-primary-hover',
    hint: '批准后将在隔离分支上生成提交',
  },
  approve_once: {
    label: '同意（仅本次）',
    cls: 'bg-primary text-primary-fg hover:bg-primary-hover',
    hint: '批准本次操作；同一工具下次操作时会再次询问',
  },
  approve_always: {
    label: '同意（后续免问）',
    cls: 'border border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-600 hover:text-slate-100',
    hint: '批准本次及本运行内后续同类操作，不再询问',
  },
  continue: {
    label: '继续迭代',
    cls: 'bg-primary text-primary-fg hover:bg-primary-hover',
    hint: '携带额外需求恢复运行，继续下一轮修复',
  },
  resume: {
    label: '继续运行',
    cls: 'bg-primary text-primary-fg hover:bg-primary-hover',
    hint: '携带补充需求恢复运行，Agent 将立即采纳',
  },
  reject: {
    label: '拒绝',
    cls: 'border border-rose-800 bg-rose-950/30 text-rose-300 hover:border-rose-600 hover:text-rose-200',
    hint: '拒绝变更，运行以 rejected 结束（不提交）',
  },
}

const SEVERITY_CLS: Record<string, string> = {
  high: 'bg-rose-950 text-rose-300',
  critical: 'bg-rose-950 text-rose-300',
  medium: 'bg-amber-950 text-amber-300',
  low: 'bg-slate-800 text-slate-400',
}

type Theme = { border: string; dot: string }

const THEMES: Record<'pause' | 'human' | 'normal', Theme> = {
  pause: {
    border: 'border-blue-700/60',
    dot: 'bg-blue-400',
  },
  human: {
    border: 'border-rose-700/60',
    dot: 'bg-rose-400',
  },
  normal: {
    border: 'border-amber-700/60',
    dot: 'bg-amber-400',
  },
}

function Chip({ cls, children }: { cls: string; children: React.ReactNode }) {
  return <span className={`shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] ${cls}`}>{children}</span>
}

function Check({ ok, label }: { ok: boolean | undefined; label: string }) {
  if (ok === undefined || ok === null) return null
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] ${ok ? 'text-emerald-400' : 'text-rose-400'}`}>
      {ok ? '✓' : '✗'} {label}
    </span>
  )
}

export function ApprovalPanel({
  runId,
  payload,
  onSubmitted,
  onViewDiff,
}: {
  runId: string
  payload: ApprovalPayload | null
  onSubmitted: () => void
  onViewDiff?: () => void
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showArgs, setShowArgs] = useState(false)
  const [showDiag, setShowDiag] = useState(false)
  const [showNote, setShowNote] = useState(false)
  const noteRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setNote('')
    setBusy(null)
    setDone(null)
    setError(null)
    setShowArgs(false)
    setShowDiag(false)
    setShowNote(payload?.type === 'pause')
    // approval_id 每次挂起唯一：同一工具再次请求审批时也能正确复位
  }, [payload?.approval_id, payload?.reason, payload?.type])

  if (!payload) return null

  const isPause = payload.type === 'pause'
  const isToolApproval = payload.type === 'tool_approval'
  const needsHuman = !!payload.needs_human
  const options = payload.options ?? ['approve', 'reject']
  const theme = isPause ? THEMES.pause : needsHuman ? THEMES.human : THEMES.normal

  const retries = payload.retries ?? {}
  const reviewIssues = payload.review_issues ?? []
  const testFailures = payload.test_failures ?? []
  const blockers = payload.blockers ?? []
  const hasDiag = needsHuman || blockers.length > 0 || reviewIssues.length > 0 || testFailures.length > 0

  const title = isPause
    ? '运行已暂停，等待你的指示'
    : isToolApproval
      ? payload.approval_mode === 'interactive'
        ? `关键操作待确认：${payload.tool ?? ''}`
        : `高风险工具待审批：${payload.tool ?? ''}`
      : needsHuman
        ? '需要人工介入：重试轮次已达上限'
        : '等待审批提交'

  const notePlaceholder = isPause
    ? '补充需求（可选）：恢复后立即注入 Agent 上下文，例如「把 README 改回去」'
    : needsHuman
      ? '额外需求 / 修复指引（可选）：点「继续迭代」后注入下一轮修复上下文'
      : '审批备注（可选，将记录在审计留痕中）'

  const noteLabel = isPause ? '补充需求' : needsHuman || options.includes('continue') ? '额外需求' : '审批备注'

  /** 一行诊断摘要（为什么停）：重试轮次 / 失败数量 */
  const diagSummary = [
    retries.code !== undefined
      ? `修复 ${retries.code}${payload.max_code_retry ? `/${payload.max_code_retry}` : ''} 轮`
      : '',
    testFailures.length > 0 ? `测试失败 ${testFailures.length} 项` : '',
    reviewIssues.length > 0 ? `审查问题 ${reviewIssues.length} 项` : '',
    blockers.length > 0 ? `阻塞 ${blockers.length} 项` : '',
  ]
    .filter(Boolean)
    .join(' · ')

  const primaryOpts = options.filter((o) => o !== 'reject')
  const rejectOpt = options.includes('reject') ? 'reject' : null

  const submit = async (decision: string) => {
    setBusy(decision)
    setError(null)
    try {
      await api.approve(runId, decision, note)
      setDone(decision)
      onSubmitted()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const openNote = () => {
    setShowNote(true)
    window.setTimeout(() => noteRef.current?.focus(), 0)
  }

  const secondaryBtn =
    'whitespace-nowrap rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100'

  return (
    <div className={`slide-up max-h-[60vh] shrink-0 overflow-y-auto border-t ${theme.border} bg-slate-900 px-4 py-3`}>
      {/* 标题行 */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`h-2 w-2 shrink-0 rounded-full ${theme.dot}`} />
        <span className="text-[13px] font-semibold text-slate-100">{title}</span>
        {isPause && <Chip cls="bg-blue-950/70 text-blue-300">已打断</Chip>}
        {needsHuman && <Chip cls="bg-rose-950/70 text-rose-300">重试达上限</Chip>}
        {isToolApproval && payload.approval_mode === 'interactive' && (
          <Chip cls="bg-slate-800 text-slate-300">逐步确认模式</Chip>
        )}
        {hasDiag && (
          <button
            onClick={() => setShowDiag((v) => !v)}
            className="ml-auto text-[11px] text-slate-500 transition-colors hover:text-slate-300"
          >
            {showDiag ? '收起详情' : '查看详情'}
          </button>
        )}
      </div>

      {/* 原因 */}
      <div className="mt-1 pl-4 text-xs leading-relaxed text-slate-300">
        {payload.reason || '请审阅变更后做出决定'}
      </div>

      {/* 关键信息摘要：进度 / 测试 / 审查 / 诊断一行摘要 / 变更文件 */}
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 pl-4 text-[11px] text-slate-400">
        {payload.tasks_total !== undefined && !isPause && (
          <span>
            任务{' '}
            <span className="text-slate-200">
              {payload.tasks_completed ?? 0}/{payload.tasks_total}
            </span>
          </span>
        )}
        {!isPause && <Check ok={payload.tests_passed} label="测试通过" />}
        {!isPause && <Check ok={payload.review_approved} label="审查通过" />}
        {diagSummary && <span className="text-amber-300">{diagSummary}</span>}
        {payload.changed_files && payload.changed_files.length > 0 && (
          <span className="flex flex-wrap items-center gap-1">
            变更 {payload.changed_files.length} 个文件:
            {payload.changed_files.slice(0, 3).map((f) => (
              <span key={f} className="rounded bg-slate-800/70 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                {f}
              </span>
            ))}
            {payload.changed_files.length > 3 && (
              <span className="text-[10px] text-slate-500">+{payload.changed_files.length - 3}</span>
            )}
          </span>
        )}
      </div>

      {/* 工具审批参数（可展开/收起） */}
      {isToolApproval && payload.arguments && (
        <div className="mt-2 pl-4">
          <button
            onClick={() => setShowArgs((v) => !v)}
            className="text-[11px] text-slate-400 transition-colors hover:text-slate-200"
          >
            {showArgs ? '▾ 收起操作参数' : `▸ 展开操作参数（${Object.keys(payload.arguments).length} 项）`}
          </button>
          {showArgs && (
            <pre className="mt-1 max-h-48 overflow-auto rounded-md border border-slate-800 bg-slate-950/80 p-2 font-mono text-[10px] leading-relaxed text-slate-400">
              {JSON.stringify(payload.arguments, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* 人工介入诊断（重试轮次 / 测试失败 / 审查问题 / 阻塞项），默认折叠 */}
      {hasDiag && showDiag && (
        <div className="mt-2 max-h-52 space-y-2 overflow-y-auto rounded-md border border-slate-800 bg-slate-950/50 p-2.5">
          {Object.keys(retries).length > 0 && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
              <span className="font-semibold text-slate-300">重试轮次</span>
              <span>
                代码修复{' '}
                <span className="text-amber-300">
                  {retries.code ?? 0}
                  {payload.max_code_retry ? `/${payload.max_code_retry}` : ''}
                </span>
              </span>
              <span>
                测试 <span className="text-slate-200">{retries.test ?? 0}</span>
              </span>
              <span>
                审查 <span className="text-slate-200">{retries.review ?? 0}</span>
              </span>
              <span>
                计划 <span className="text-slate-200">{retries.plan ?? 0}</span>
              </span>
            </div>
          )}
          {blockers.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-rose-300">阻塞项 ({blockers.length})</div>
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-[11px] text-slate-400">
                {blockers.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          )}
          {testFailures.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-rose-300">测试失败 ({testFailures.length})</div>
              <ul className="mt-1 space-y-1 text-[11px] text-slate-400">
                {testFailures.map((f, i) => (
                  <li key={i} className="rounded bg-slate-900/70 px-2 py-1 font-mono">
                    <span className="text-rose-300">{f.test || f.file || '未命名用例'}</span>
                    {f.message && <span className="block text-slate-500">{f.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {reviewIssues.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-amber-300">审查问题 ({reviewIssues.length})</div>
              <ul className="mt-1 space-y-1 text-[11px] text-slate-400">
                {reviewIssues.map((iss, i) => (
                  <li key={i} className="rounded bg-slate-900/70 px-2 py-1">
                    <span
                      className={`mr-1.5 rounded px-1 py-0.5 text-[10px] uppercase ${
                        SEVERITY_CLS[String(iss.severity ?? '').toLowerCase()] ?? 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {iss.severity || 'info'}
                    </span>
                    {iss.file && <span className="font-mono text-slate-300">{iss.file}</span>}
                    {iss.problem && <span className="block text-slate-400">{iss.problem}</span>}
                    {iss.suggestion && <span className="block text-slate-500">建议：{iss.suggestion}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* 备注输入（pause 默认展开；其余折叠在「补充指令」按钮后） */}
      {showNote && (
        <div className="mt-2 pl-4">
          <input
            ref={noteRef}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={notePlaceholder}
            className="w-full rounded-md border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500"
            disabled={!!done}
          />
        </div>
      )}

      {/* 操作行：主操作 → 次操作 → 危险操作（右侧） */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 pl-4">
        {done ? (
          <span className="text-xs text-emerald-400">
            已提交「{DECISION_UI[done]?.label ?? done}」，运行恢复中…（状态将自动刷新）
          </span>
        ) : (
          <>
            {primaryOpts.map((opt) => {
              const ui = DECISION_UI[opt] ?? {
                label: opt,
                cls: 'bg-slate-700 hover:bg-slate-600 text-white',
                hint: '',
              }
              return (
                <button
                  key={opt}
                  title={ui.hint}
                  onClick={() => void submit(opt)}
                  disabled={!!busy}
                  className={`whitespace-nowrap rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${ui.cls}`}
                >
                  {busy === opt ? '提交中…' : ui.label}
                </button>
              )
            })}
            {onViewDiff && !isPause && (
              <button onClick={onViewDiff} className={secondaryBtn}>
                查看 Diff
              </button>
            )}
            {!isPause && !showNote && (
              <button onClick={openNote} className={secondaryBtn}>
                + {noteLabel}
              </button>
            )}
            {rejectOpt && (
              <button
                title={isPause ? '取消本次运行（不提交），已产生的变更保留在工作区' : DECISION_UI.reject.hint}
                onClick={() => void submit(rejectOpt)}
                disabled={!!busy}
                className={`ml-auto whitespace-nowrap rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${DECISION_UI.reject.cls}`}
              >
                {busy === rejectOpt ? '提交中…' : isPause ? '取消运行' : DECISION_UI.reject.label}
              </button>
            )}
          </>
        )}
      </div>
      {error && <div className="mt-1.5 pl-4 text-xs text-rose-400">{error}</div>}
    </div>
  )
}
