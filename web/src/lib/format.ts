/** 格式化工具。 */

export function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

/** 友好的短时间戳：今天 HH:mm / 昨天 HH:mm / MM-DD HH:mm（列表行用）。 */
export function fmtShortDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  if (d.toDateString() === now.toDateString()) return `今天 ${hm}`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `昨天 ${hm}`
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`
}

export function fmtCost(v: number | null | undefined): string {
  return `$${(v ?? 0).toFixed(4)}`
}

export function fmtTokens(v: number | null | undefined): string {
  const n = v ?? 0
  if (n >= 1000000) return `${(n / 1000000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export function fmtDuration(seconds: number | null | undefined): string {
  const s = Math.round(seconds ?? 0)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m < 60) return `${m}m ${r}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export function fmtPercent(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${Math.round(v * 100)}%`
}

export function shortId(id: string): string {
  return id.slice(0, 8)
}
