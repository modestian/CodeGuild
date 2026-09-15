/** 运行指标面板：Token / 成本 / 效率统计（Recharts 可视化）。 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { Metrics } from '../api/types'
import { fmtCost, fmtDuration, fmtPercent, fmtTokens } from '../lib/format'
import { useThemeMode } from '../lib/theme'

const num = (m: Metrics, k: string): number => {
  const v = m[k]
  return typeof v === 'number' ? v : 0
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-slate-900 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-base font-semibold ${accent ?? 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

export function MetricsPanel({ metrics }: { metrics: Metrics }) {
  const dark = useThemeMode() === 'dark'
  const chart = dark
    ? { grid: '#1e293b', tick: '#64748b', cursor: '#1e293b55', tipBg: '#0f172a', tipBorder: '#1e293b', tipLabel: '#94a3b8' }
    : { grid: '#e2e8f0', tick: '#64748b', cursor: '#e2e8f055', tipBg: '#ffffff', tipBorder: '#e2e8f0', tipLabel: '#475569' }
  const inputTokens = num(metrics, 'input_tokens')
  const outputTokens = num(metrics, 'output_tokens')
  const tokenData = [
    { name: '输入', tokens: inputTokens, fill: '#2563eb' },
    { name: '输出', tokens: outputTokens, fill: '#60a5fa' },
  ]

  const testsTotal = num(metrics, 'summary_total')
  const passRate = typeof metrics['test_pass_rate'] === 'number' ? (metrics['test_pass_rate'] as number) : null

  return (
    <div className="space-y-3 p-3">
      <div className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-slate-800 bg-slate-800">
        <Stat label="成本" value={fmtCost(num(metrics, 'cost_usd'))} />
        <Stat label="Tokens" value={fmtTokens(inputTokens + outputTokens)} />
        <Stat label="耗时" value={fmtDuration(num(metrics, 'execution_seconds'))} />
        <Stat label="工具调用" value={String(num(metrics, 'tool_calls'))} />
        <Stat label="Agent 调用" value={String(num(metrics, 'agent_runs'))} />
        <Stat label="重试次数" value={String(num(metrics, 'retry_count'))} />
        <Stat label="任务完成" value={`${num(metrics, 'tasks_completed')}/${num(metrics, 'tasks_total')}`} />
        <Stat
          label="测试通过率"
          value={passRate !== null ? fmtPercent(passRate) : testsTotal ? fmtPercent(1) : '—'}
          accent={passRate !== null && passRate >= 1 ? 'text-emerald-300' : undefined}
        />
        <Stat
          label="任务成功"
          value={metrics['task_success'] === true ? '是' : metrics['task_success'] === false ? '否' : '—'}
        />
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
        <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">Token 消耗</div>
        <ResponsiveContainer width="100%" height={150}>
          <BarChart data={tokenData} margin={{ top: 4, right: 8, bottom: 0, left: -14 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: chart.tick, fontSize: 11 }} axisLine={{ stroke: chart.grid }} tickLine={false} />
            <YAxis tick={{ fill: chart.tick, fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: chart.cursor }}
              contentStyle={{ background: chart.tipBg, border: `1px solid ${chart.tipBorder}`, borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: chart.tipLabel }}
            />
            <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
              {tokenData.map((d) => (
                <Cell key={d.name} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="text-[10px] leading-relaxed text-slate-600">
        工具执行耗时 {fmtDuration(num(metrics, 'tool_time_ms') / 1000)} · 审批 {num(metrics, 'approvals')} 次 ·
        路由决策 {num(metrics, 'routing_decisions')} 次 · 文件变更 {num(metrics, 'files_changed')} 个
      </div>
    </div>
  )
}
