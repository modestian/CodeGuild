/** 审批留痕抽屉（FR-HITL-06 可审计）：工具级审批 + 人工交付决策的完整历史。 */
import type { ApprovalRecord } from '../api/client'
import { useApprovals } from '../api/hooks'
import { fmtDateTime } from '../lib/format'

const STATUS_UI: Record<string, { label: string; cls: string; dot: string }> = {
  pending: { label: '待审批', cls: 'bg-amber-950/80 text-amber-300 border-amber-800', dot: 'bg-amber-400' },
  approved: { label: '已批准', cls: 'bg-emerald-950/80 text-emerald-300 border-emerald-800', dot: 'bg-emerald-400' },
  rejected: { label: '已拒绝', cls: 'bg-rose-950/80 text-rose-300 border-rose-800', dot: 'bg-rose-400' },
}

const DECISION_LABEL: Record<string, string> = {
  approve: '批准并提交',
  approve_once: '同意（仅本次）',
  approve_always: '同意（后续免问）',
  continue: '继续迭代',
  reject: '拒绝',
}

const SCOPE_LABEL: Record<string, { label: string; cls: string }> = {
  once: { label: '仅本次', cls: 'bg-slate-800 text-slate-400' },
  always: { label: '本次运行免问', cls: 'bg-slate-800 text-slate-300' },
}

const RISK_CLS: Record<string, string> = {
  LOW: 'bg-slate-800 text-slate-400',
  MEDIUM: 'bg-amber-950 text-amber-300',
  HIGH: 'bg-rose-950 text-rose-300',
  CRITICAL: 'bg-rose-900 text-rose-200',
}

const TOOL_LABEL: Record<string, string> = {
  human_approval: '人工交付审批',
}

function RecordCard({ record }: { record: ApprovalRecord }) {
  const status = STATUS_UI[record.status] ?? STATUS_UI.pending
  const decision = typeof record.arguments?.decision === 'string' ? record.arguments.decision : ''
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-medium ${status.cls}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        <span className="font-mono text-[11px] text-slate-300">{TOOL_LABEL[record.tool] ?? record.tool}</span>
        {record.risk_level && (
          <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${RISK_CLS[record.risk_level] ?? RISK_CLS.MEDIUM}`}>
            {record.risk_level}
          </span>
        )}
        {decision && (
          <span className="ml-auto rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
            {DECISION_LABEL[decision] ?? decision}
          </span>
        )}
        {!decision && record.status !== 'pending' && record.tool !== 'human_approval' && record.scope && (
          <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] ${(SCOPE_LABEL[record.scope] ?? SCOPE_LABEL.once).cls}`}>
            {record.consumed ? '已消费 · ' : ''}
            {(SCOPE_LABEL[record.scope] ?? SCOPE_LABEL.once).label}
          </span>
        )}
      </div>

      {record.reason && <div className="mt-2 text-xs leading-relaxed text-slate-400">{record.reason}</div>}
      {record.note && (
        <div className="mt-1.5 rounded border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 text-[11px] leading-relaxed text-slate-400">
          <span className="text-slate-600">备注：</span>
          {record.note}
        </div>
      )}

      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-slate-600">
        <span>
          请求 {fmtDateTime(record.requested_at)}
          {record.decided_at && ` · 决定 ${fmtDateTime(record.decided_at)}`}
        </span>
        <span>{record.decided_by ? `by ${record.decided_by}` : ''}</span>
      </div>
    </div>
  )
}

export function ApprovalHistory({ runId, open, onClose }: { runId: string; open: boolean; onClose: () => void }) {
  const { data, error } = useApprovals(runId, open)
  if (!open) return null

  const records = data?.approvals ?? []

  return (
    <aside className="slide-up fixed bottom-0 right-0 top-14 z-30 flex w-[400px] flex-col border-l border-slate-800 bg-slate-900 shadow-lg">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-slate-800/60 px-3">
        <span className="text-[13px] font-semibold text-slate-300">
          审批留痕 <span className="ml-1 text-[11px] font-normal text-slate-500">可审计 · {records.length} 条</span>
        </span>
        <button onClick={onClose} className="text-xs text-slate-500 hover:text-slate-300">
          关闭 ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {error && <div className="text-xs text-rose-400">加载失败：{error}</div>}
        {!error && records.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <span className="text-sm text-slate-500">暂无审批记录</span>
            <span className="max-w-[260px] text-xs leading-relaxed text-slate-600">
              逐步确认模式下的关键操作审批、高风险工具审批与人工交付决策将在此留痕（含「仅本次/免问」范围）
            </span>
          </div>
        )}
        {records.map((r) => (
          <RecordCard key={r.id} record={r} />
        ))}
      </div>
    </aside>
  )
}
