/**
 * 项目工作台（/）：Repository Context → New Development Task → Recent Runs。
 * 依据 docs/project_workspace_ui_design.md：
 * - 左栏为仓库导航（Repository Sidebar），选中项承载运行统计
 * - 「发起开发任务」是页面第一操作焦点与唯一最强 CTA（bg-primary）
 * - 运行历史以任务描述为第一信息，Run ID 降级为 metadata，默认 8 条不内部滚动
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useProject, useProjects } from '../api/hooks'
import type { RunBrief, RunInfo } from '../api/types'
import { StatusBadge } from '../components/badges'
import { ThemeToggle } from '../components/ThemeToggle'
import { fmtCost, fmtShortDateTime, shortId } from '../lib/format'

/** 最近运行默认展示条数（规范 §11：6~8 条，超出后手动展开，避免内部滚动）。 */
const DEFAULT_VISIBLE_RUNS = 8

export function ProjectsPage() {
  const navigate = useNavigate()
  const { data: projData, refresh: refreshProjects } = useProjects()
  const projects = useMemo(() => projData?.projects ?? [], [projData])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  useEffect(() => {
    if (!selectedId && projects.length) setSelectedId(projects[0].id)
  }, [projects, selectedId])

  const { data: detail, refresh: refreshDetail } = useProject(selectedId ?? undefined)

  // 新建仓库表单
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newRepo, setNewRepo] = useState('')
  const [initIfNeeded, setInitIfNeeded] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const importRef = useRef<HTMLDivElement>(null)

  /** 打开导入表单并将表单滚动到可见区域（侧栏 / 空态入口共用）。 */
  const openImport = () => {
    setShowNew(true)
    window.setTimeout(() => importRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 60)
  }

  // 发起任务表单
  const [request, setRequest] = useState('')
  const [approvalMode, setApprovalMode] = useState<'interactive' | 'auto'>('interactive')
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  // 选中仓库的运行统计（侧栏选中卡片展示）
  const stats = useMemo(() => {
    const runs = detail?.runs ?? []
    const terminal = runs.filter((r) => ['completed', 'failed', 'rejected', 'cancelled'].includes(r.status))
    const ok = runs.filter((r) => r.status === 'completed').length
    const lastRunAt = runs.reduce<string | null>(
      (acc, r) => (r.created_at && (!acc || r.created_at > acc) ? r.created_at : acc),
      null,
    )
    return {
      total: runs.length,
      successRate: terminal.length ? Math.round((ok / terminal.length) * 100) : null,
      lastRunAt,
    }
  }, [detail])

  const onAddProject = async () => {
    if (!newName.trim() || !newRepo.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const p = await api.createProject({
        name: newName.trim(),
        repo_path: newRepo.trim(),
        init_if_needed: initIfNeeded,
      })
      setShowNew(false)
      setNewName('')
      setNewRepo('')
      await refreshProjects()
      setSelectedId(p.id)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const onStartRun = async () => {
    if (!selectedId || !request.trim()) return
    setStarting(true)
    setStartError(null)
    try {
      const { run } = await api.createRun(selectedId, request.trim(), approvalMode)
      navigate(`/run/${run.id}`)
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e))
      setStarting(false)
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[1280px] flex-col gap-6 overflow-y-auto px-8 py-7">
      {/* ---------- Header ---------- */}
      <header className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold leading-8 tracking-tight text-slate-100">项目工作台</h1>
          <p className="mt-1 text-[13px] text-slate-500">管理代码仓库并发起 AI 软件开发任务</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => (showNew ? setShowNew(false) : openImport())}
            className="whitespace-nowrap rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-slate-800/60 hover:text-slate-100"
          >
            {showNew ? '收起' : '+ 导入项目'}
          </button>
        </div>
      </header>

      {/* ---------- 导入项目（次级操作，展开后内联表单） ---------- */}
      {showNew && (
        <div ref={importRef} className="slide-up rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[200px_1fr_auto] md:items-end">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-slate-500">项目名称</span>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="my-project"
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-slate-500">项目文件夹绝对路径</span>
              <input
                value={newRepo}
                onChange={(e) => setNewRepo(e.target.value)}
                placeholder="D:\projects\my-app"
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500"
              />
            </label>
            <button
              onClick={() => void onAddProject()}
              disabled={creating || !newName.trim() || !newRepo.trim()}
              className="whitespace-nowrap rounded-md border border-slate-600 bg-slate-800/80 px-4 py-1.5 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-700 disabled:opacity-40"
            >
              {creating ? '导入中…' : '导入'}
            </button>
          </div>
          <label className="mt-3 flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={initIfNeeded}
              onChange={(e) => setInitIfNeeded(e.target.checked)}
              className="h-3.5 w-3.5 accent-blue-500"
            />
            <span className="text-[11px] text-slate-500">
              不是 Git 仓库（或尚无提交）时自动初始化：执行 git init 并创建基线提交，不改动现有文件
            </span>
          </label>
          {createError && <div className="mt-2 text-xs text-rose-400">{createError}</div>}
        </div>
      )}

      {projData === null ? (
        <div className="flex flex-1 items-center justify-center text-xs text-slate-500">正在加载…</div>
      ) : projects.length === 0 ? (
        /* ---------- 无仓库空态 ---------- */
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-800 py-16 text-center">
          <p className="text-sm text-slate-300">还没有导入项目</p>
          <p className="text-xs text-slate-500">导入本地项目文件夹（Git 或普通文件夹均可），即可向 AI 开发 Agent 发起任务</p>
          <button
            onClick={openImport}
            className="mt-2 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-fg transition-colors hover:bg-primary-hover"
          >
            + 导入项目
          </button>
        </div>
      ) : (
        <>
          {/* ---------- Repository Sidebar | New Development Task ---------- */}
          <div className="grid items-start gap-6 min-[1200px]:grid-cols-[300px_1fr]">
            <aside className="hidden flex-col gap-3 md:flex">
              <div className="flex items-center justify-between px-0.5">
                <h2 className="text-sm font-semibold text-slate-200">仓库</h2>
                <span className="text-[11px] text-slate-500">{projects.length} 个</span>
              </div>
              {projects.map((p) => {
                const active = p.id === selectedId
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelectedId(p.id)}
                    className={`rounded-lg border p-3.5 text-left transition-colors ${
                      active
                        ? 'border-blue-600/60 bg-blue-950/25'
                        : 'border-slate-800 bg-slate-900/50 hover:border-slate-700 hover:bg-slate-900'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? 'bg-blue-400' : 'bg-slate-600'}`} />
                      <span className="truncate text-[13px] font-medium text-slate-100">{p.name}</span>
                    </div>
                    <div className="mt-1.5 truncate pl-3.5 font-mono text-[11px] text-slate-500">
                      {p.default_branch || 'HEAD'} · #{shortId(p.id)}
                    </div>
                    <div className="mt-1 truncate pl-3.5 font-mono text-[11px] text-slate-600" title={p.repo_path}>
                      {p.repo_path}
                    </div>
                    {active && detail && (
                      <div className="mt-2.5 border-t border-slate-800/60 pl-3.5 pt-2.5 text-[11px] leading-relaxed text-slate-500">
                        {stats.total === 0 ? (
                          '暂无运行记录'
                        ) : (
                          <>
                            共 {stats.total} 次运行
                            {stats.successRate !== null && ` · 成功率 ${stats.successRate}%`}
                            {stats.lastRunAt && ` · 最近 ${fmtShortDateTime(stats.lastRunAt)}`}
                          </>
                        )}
                      </div>
                    )}
                  </button>
                )
              })}
              <button
                onClick={openImport}
                className="rounded-lg border border-dashed border-slate-800 py-2.5 text-xs text-slate-500 transition-colors hover:border-slate-700 hover:text-slate-300"
              >
                + 导入项目
              </button>
            </aside>

            {/* ---------- New Development Task（页面第一操作焦点） ---------- */}
            <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-5">
              {/* Mobile：仓库选择器（<768px 时替代侧栏） */}
              <div className="mb-4 md:hidden">
                <label className="mb-1 block text-[11px] text-slate-500">当前仓库</label>
                <select
                  value={selectedId ?? projects[0]?.id ?? ''}
                  onChange={(e) => setSelectedId(e.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-[13px] text-slate-200 outline-none focus:border-blue-500"
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="text-[15px] font-semibold text-slate-100">发起开发任务</h2>
                  <p className="mt-0.5 text-xs text-slate-500">用自然语言描述你希望 Agent 在当前仓库完成的工作</p>
                </div>
                {detail && (
                  <span className="shrink-0 rounded border border-slate-700 bg-slate-900/70 px-2 py-1 font-mono text-[11px] text-slate-400">
                    {detail.project.name} · {detail.project.default_branch || 'HEAD'}
                  </span>
                )}
              </div>

              <textarea
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                rows={5}
                placeholder={
                  '例如：\n为 NoteStore 增加搜索功能；\n修复 delete(index) 越界抛出 IndexError 的问题；\n为登录流程补充 JWT 过期校验。'
                }
                className="mt-4 min-h-[120px] w-full resize-none rounded-md border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500"
              />

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <span className="text-xs text-slate-400">执行模式</span>
                <div className="flex rounded-md border border-slate-700 p-0.5">
                  <button
                    onClick={() => setApprovalMode('interactive')}
                    className={`rounded px-2.5 py-1 text-xs transition-colors ${
                      approvalMode === 'interactive'
                        ? 'bg-primary text-primary-fg'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    逐步确认
                  </button>
                  <button
                    onClick={() => setApprovalMode('auto')}
                    className={`rounded px-2.5 py-1 text-xs transition-colors ${
                      approvalMode === 'auto'
                        ? 'bg-primary text-primary-fg'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    自动执行
                  </button>
                </div>
                <button
                  onClick={() => void onStartRun()}
                  disabled={starting || !request.trim() || !selectedId}
                  className="ml-auto shrink-0 whitespace-nowrap rounded-md bg-primary px-6 py-2 text-[13px] font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:opacity-40"
                >
                  {starting ? '发起中…' : '发起任务'}
                </button>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                {approvalMode === 'interactive'
                  ? '逐步确认：Agent 会在关键代码修改、提交和危险操作前等待你的确认。'
                  : '自动执行：Agent 会在授权范围内持续推进，异常或高风险操作时才暂停。'}
              </p>
              {startError && <div className="mt-2 text-xs text-rose-400">{startError}</div>}
            </section>
          </div>

          {/* ---------- Recent Runs（全宽任务历史） ---------- */}
          {detail && <RecentRuns key={selectedId} runs={detail.runs} onRefresh={refreshDetail} />}
        </>
      )}
    </div>
  )
}

/**
 * 最近运行列表：任务描述为第一信息，Run ID / 费用为 metadata；
 * 默认 8 条，超出后手动展开（不产生内部滚动条）。
 * 任务描述通过 api.getRun 增量获取并缓存（RunBrief 不含 request）。
 */
function RecentRuns({ runs, onRefresh }: { runs: RunBrief[]; onRefresh: () => void | Promise<void> }) {
  const navigate = useNavigate()
  const [showAll, setShowAll] = useState(false)
  const [infos, setInfos] = useState<Record<string, RunInfo>>({})
  const infosRef = useRef(infos)
  infosRef.current = infos
  const attemptedRef = useRef<Set<string>>(new Set())

  const visible = useMemo(
    () => (showAll ? runs : runs.slice(0, DEFAULT_VISIBLE_RUNS)),
    [runs, showAll],
  )

  useEffect(() => {
    const need = visible
      .map((r) => r.id)
      .filter((id) => !infosRef.current[id] && !attemptedRef.current.has(id))
    if (!need.length) return
    need.forEach((id) => attemptedRef.current.add(id))
    let cancelled = false
    void Promise.allSettled(need.map((id) => api.getRun(id))).then((results) => {
      if (cancelled) return
      setInfos((prev) => {
        const next = { ...prev }
        results.forEach((res, i) => {
          if (res.status === 'fulfilled') next[need[i]] = res.value
        })
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [visible])

  return (
    <section className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50">
      <header className="flex items-center gap-2.5 border-b border-slate-800/60 px-5 py-3">
        <h2 className="text-[15px] font-semibold text-slate-100">最近运行</h2>
        <span className="text-xs text-slate-500">共 {runs.length} 次</span>
        <button
          onClick={() => void onRefresh()}
          className="ml-auto text-xs text-slate-500 transition-colors hover:text-slate-300"
        >
          刷新
        </button>
      </header>

      {runs.length === 0 ? (
        <div className="px-5 py-10 text-center text-xs text-slate-500">
          暂无运行记录 —— 在上方输入需求并发起第一个任务
        </div>
      ) : (
        <>
          {visible.map((r) => {
            const info = infos[r.id]
            const cost = info?.metrics?.cost_usd
            return (
              <button
                key={r.id}
                onClick={() => navigate(`/run/${r.id}`)}
                className="flex w-full items-center gap-4 border-b border-slate-800/40 px-5 py-3 text-left transition-colors last:border-0 hover:bg-slate-800/40"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] text-slate-200" title={info?.request}>
                    {info?.request ?? '…'}
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-slate-600">
                    #{shortId(r.id)}
                    {typeof cost === 'number' && cost > 0 && <span> · {fmtCost(cost)}</span>}
                  </div>
                </div>
                <span className="flex w-[88px] shrink-0">
                  <StatusBadge status={r.status} size="sm" />
                </span>
                <span className="hidden w-[104px] shrink-0 text-right font-mono text-[11px] text-slate-500 sm:block">
                  {fmtShortDateTime(r.created_at)}
                </span>
              </button>
            )
          })}
          {runs.length > DEFAULT_VISIBLE_RUNS && (
            <div className="border-t border-slate-800/60 px-5 py-1.5">
              <button
                onClick={() => setShowAll((v) => !v)}
                className="w-full py-1 text-center text-xs text-slate-500 transition-colors hover:text-slate-300"
              >
                {showAll ? '收起' : `查看全部 ${runs.length} 条运行记录`}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
