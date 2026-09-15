/** 运行详情页：三栏布局（Task DAG | Agent 执行轨迹 | AI 解说·实时交流）
 * - 三栏支持拖动调宽（宽屏），宽度持久化到 localStorage
 * - medium（<1180px）：AI 交流折叠为抽屉；narrow（<820px）：改为标签页
 * - 底部 Contextual 审批面板（仅挂起时出现）+ 右上角 Diff / 指标抽屉
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApprovalHistory } from '../components/ApprovalHistory'
import { ApprovalPanel } from '../components/ApprovalPanel'
import { ArtifactViewer } from '../components/ArtifactViewer'
import { DiffViewer } from '../components/DiffViewer'
import { EventTrace } from '../components/EventTrace'
import { MetricsPanel } from '../components/MetricsPanel'
import { NarrativeChat } from '../components/NarrativeChat'
import { RunHeader } from '../components/RunHeader'
import { TaskDag } from '../components/TaskDag'
import { TaskDetail } from '../components/TaskDetail'
import { api } from '../api/client'
import { useArtifacts, useDiff, useRun, useRunEvents, useRunState, useTasks } from '../api/hooks'
import { isTerminal } from '../api/types'
import { fmtDateTime } from '../lib/format'

const DIFF_TRIGGER_TYPES = new Set(['task_completed', 'repairing', 'review_result', 'diff_ready', 'test_result'])

type LayoutMode = 'wide' | 'medium' | 'narrow'
type NarrowTab = 'tasks' | 'activity' | 'chat'

const DAG_WIDTH = { default: 280, min: 224, max: 380 }
const CHAT_WIDTH = { default: 360, min: 300, max: 480 }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

function loadWidth(key: string, fallback: number, lo: number, hi: number): number {
  try {
    const raw = Number(localStorage.getItem(key))
    if (Number.isFinite(raw) && raw > 0) return clamp(raw, lo, hi)
  } catch {
    // localStorage 不可用时使用默认值
  }
  return fallback
}

function PaneHeader({ title, extra }: { title: string; extra?: React.ReactNode }) {
  return (
    <div className="flex h-9 shrink-0 items-center gap-2 overflow-hidden border-b border-slate-800/60 px-3">
      <span className="shrink-0 whitespace-nowrap text-[13px] font-semibold text-slate-300">{title}</span>
      <div className="ml-auto flex min-w-0 items-center gap-2 whitespace-nowrap text-[11px] text-slate-500">
        {extra}
      </div>
    </div>
  )
}

function DragHandle({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) {
  return (
    <div
      onMouseDown={onMouseDown}
      title="拖动调整栏宽"
      className="group relative w-px shrink-0 cursor-col-resize bg-slate-800/60"
    >
      <div className="absolute inset-y-0 -left-1 -right-1 transition-colors group-hover:bg-blue-500/30" />
    </div>
  )
}

export function RunPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()

  const { data: run, refresh: refreshRun } = useRun(runId)
  const active = !isTerminal(run?.status)
  const { data: tasksData, refresh: refreshTasks } = useTasks(runId, !run || !isTerminal(run.status))
  const { data: stateData, refresh: refreshState } = useRunState(runId, !run || !isTerminal(run.status))
  const { events, connected, ended } = useRunEvents(runId, run?.status)

  // 关键事件驱动 diff 刷新 + 手动刷新
  const [manualDiffTok, setManualDiffTok] = useState(0)
  const diffTrigger = useMemo(
    () => events.filter((e) => DIFF_TRIGGER_TYPES.has(e.type)).length,
    [events],
  )
  const { data: diffData, refresh: refreshDiff } = useDiff(runId, diffTrigger + manualDiffTok)

  const [showMetrics, setShowMetrics] = useState(false)
  const [showArtifacts, setShowArtifacts] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showDiff, setShowDiff] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [modeBusy, setModeBusy] = useState(false)
  const [cancelBusy, setCancelBusy] = useState(false)
  const [pauseBusy, setPauseBusy] = useState(false)
  const [pauseAsked, setPauseAsked] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // ---- 布局：宽屏三栏可拖动 / medium 折叠交流 / narrow 标签页 ----
  const computeLayout = (): LayoutMode => {
    const w = window.innerWidth
    return w >= 1180 ? 'wide' : w >= 820 ? 'medium' : 'narrow'
  }
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(computeLayout)
  useEffect(() => {
    const onResize = () => setLayoutMode(computeLayout())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const [dagW, setDagW] = useState(() =>
    loadWidth('runpage.dagWidth', DAG_WIDTH.default, DAG_WIDTH.min, DAG_WIDTH.max),
  )
  const [chatW, setChatW] = useState(() =>
    loadWidth('runpage.chatWidth', CHAT_WIDTH.default, CHAT_WIDTH.min, CHAT_WIDTH.max),
  )
  const [chatOpen, setChatOpen] = useState(true)
  const [narrowTab, setNarrowTab] = useState<NarrowTab>('activity')

  useEffect(() => {
    try {
      localStorage.setItem('runpage.dagWidth', String(dagW))
    } catch {
      // 忽略持久化失败
    }
  }, [dagW])
  useEffect(() => {
    try {
      localStorage.setItem('runpage.chatWidth', String(chatW))
    } catch {
      // 忽略持久化失败
    }
  }, [chatW])

  const dragRef = useRef<{ which: 'dag' | 'chat'; startX: number; startW: number } | null>(null)
  const startDrag = (which: 'dag' | 'chat') => (e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { which, startX: e.clientX, startW: which === 'dag' ? dagW : chatW }
    document.body.classList.add('is-resizing')
    const onMove = (ev: MouseEvent) => {
      const drag = dragRef.current
      if (!drag) return
      const dx = ev.clientX - drag.startX
      if (drag.which === 'dag') setDagW(clamp(drag.startW + dx, DAG_WIDTH.min, DAG_WIDTH.max))
      else setChatW(clamp(drag.startW - dx, CHAT_WIDTH.min, CHAT_WIDTH.max))
    }
    const onUp = () => {
      dragRef.current = null
      document.body.classList.remove('is-resizing')
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const { data: artifactsData } = useArtifacts(runId, !run || !isTerminal(run.status))
  const artifactMetas = useMemo(() => artifactsData?.artifacts ?? [], [artifactsData])

  const tasks = useMemo(() => tasksData?.tasks ?? [], [tasksData])
  const completedCount = tasks.filter((t) => t.status === 'COMPLETED').length
  const selectedTask = useMemo(
    () => tasks.find((t) => t.id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  )
  // 终态后忽略缓存的挂起载荷（避免取消/完成后底部审批面板残留）
  const pendingApproval = active ? (stateData?.pending_approval ?? null) : null
  const isPaused = pendingApproval?.type === 'pause'
  // 等待人工输入期间（待审批/需人工介入）无需打断，禁用按钮避免 409
  const canPause =
    !!run && active && !isPaused && run.status !== 'waiting_approval' && run.status !== 'needs_human'
  const metrics = run?.metrics ?? {}

  // 恢复运行后（pause_resumed 事件）允许再次打断
  const pauseResumeCount = useMemo(() => events.filter((e) => e.type === 'pause_resumed').length, [events])
  useEffect(() => {
    setPauseAsked(false)
  }, [pauseResumeCount])

  const refreshAll = () => {
    void refreshRun()
    void refreshTasks()
    void refreshState()
    void refreshDiff()
    setManualDiffTok((v) => v + 1)
  }

  const toggleDiff = () => {
    setShowDiff((v) => !v)
    setManualDiffTok((v) => v + 1)
  }

  // 运行级审批模式切换：auto ↔ interactive
  const toggleApprovalMode = async () => {
    if (!runId || modeBusy) return
    setModeBusy(true)
    setActionError(null)
    try {
      await api.setApprovalMode(runId, run?.approval_mode === 'interactive' ? 'auto' : 'interactive')
      await refreshRun()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setModeBusy(false)
    }
  }

  // 人工打断：下一个安全点暂停，随后可在暂停面板补充需求
  const onPauseRun = async () => {
    if (!runId || pauseBusy || pauseAsked) return
    setPauseBusy(true)
    setActionError(null)
    try {
      await api.requestPause(runId)
      setPauseAsked(true)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setPauseBusy(false)
    }
  }

  // 人工终止运行
  const onCancelRun = async () => {
    if (!runId || cancelBusy) return
    if (!window.confirm('确定终止该运行？已产生的变更保留在工作区，不会自动提交。')) return
    setCancelBusy(true)
    setActionError(null)
    try {
      await api.cancelRun(runId)
      refreshAll()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setCancelBusy(false)
    }
  }

  if (!runId) {
    navigate('/')
    return null
  }

  const dagPane = (
    <section
      style={layoutMode === 'wide' ? { width: dagW } : undefined}
      className={`flex shrink-0 flex-col ${layoutMode === 'medium' ? 'w-[264px]' : ''}`}
    >
      <PaneHeader
        title="任务图"
        extra={
          <span>
            {completedCount}/{tasks.length} 完成
          </span>
        }
      />
      <div className="min-h-0 flex-1">
        <TaskDag tasks={tasks} onSelect={setSelectedTaskId} />
      </div>
    </section>
  )

  const activityPane = (
    <section className="flex min-w-0 flex-1 flex-col">
      <PaneHeader title="执行轨迹" extra={<span>更新于 {fmtDateTime(run?.updated_at)}</span>} />
      <div className="min-h-0 flex-1">
        <EventTrace events={events} connected={connected} ended={ended} />
      </div>
    </section>
  )

  const chatPane = (
    <section
      style={layoutMode === 'wide' ? { width: chatW } : undefined}
      className="flex min-w-0 shrink-0 flex-col"
    >
      <PaneHeader title="AI 解说 · 交流" />
      <div className="min-h-0 flex-1">
        <NarrativeChat runId={runId} events={events} active={active} />
      </div>
    </section>
  )

  return (
    <div className="relative flex h-screen flex-col overflow-hidden bg-slate-950">
      {/* ================= Header ================= */}
      <RunHeader
        run={run}
        runId={runId}
        active={active}
        canPause={canPause}
        isPaused={isPaused}
        pauseBusy={pauseBusy}
        pauseAsked={pauseAsked}
        onPause={onPauseRun}
        cancelBusy={cancelBusy}
        onCancel={onCancelRun}
        modeBusy={modeBusy}
        onToggleMode={() => void toggleApprovalMode()}
        showDiff={showDiff}
        onToggleDiff={toggleDiff}
        showMetrics={showMetrics}
        onToggleMetrics={() => setShowMetrics((v) => !v)}
        onOpenArtifacts={() => setShowArtifacts(true)}
        onOpenHistory={() => setShowHistory(true)}
        onRefresh={refreshAll}
        artifactCount={artifactMetas.length}
        chatToggleLabel={layoutMode === 'medium' ? (chatOpen ? '收起交流' : '交流') : null}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((v) => !v)}
      />

      {/* 操作错误提示 */}
      {actionError && (
        <div className="absolute right-4 top-16 z-40 flex items-center gap-2 rounded-md border border-rose-800 bg-rose-950/95 px-3 py-2 text-xs text-rose-200 shadow-lg">
          {actionError}
          <button onClick={() => setActionError(null)} className="text-rose-400 hover:text-rose-200">
            ✕
          </button>
        </div>
      )}

      {/* 错误横幅 */}
      {run?.error && (
        <div className="shrink-0 border-b border-rose-900/50 bg-rose-950/30 px-4 py-2 text-xs text-rose-300">
          <span className="font-semibold">运行错误：</span>
          {run.error}
        </div>
      )}

      {/* ================= 主体 ================= */}
      <main className="relative flex min-h-0 flex-1">
        {layoutMode === 'narrow' ? (
          /* 窄屏：标签页 [任务][轨迹][交流] */
          <section className="flex min-w-0 flex-1 flex-col">
            <div role="tablist" className="flex h-9 shrink-0 items-center gap-1 border-b border-slate-800/60 px-2">
              {(
                [
                  { id: 'tasks', label: `任务 ${completedCount}/${tasks.length}` },
                  { id: 'activity', label: '执行轨迹' },
                  { id: 'chat', label: 'AI 交流' },
                ] as { id: NarrowTab; label: string }[]
              ).map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={narrowTab === t.id}
                  onClick={() => setNarrowTab(t.id)}
                  className={`whitespace-nowrap rounded-md px-2.5 py-1 text-xs transition-colors ${
                    narrowTab === t.id
                      ? 'bg-slate-800 text-slate-100'
                      : 'text-slate-500 hover:bg-slate-800/50 hover:text-slate-300'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1">
              {narrowTab === 'tasks' && <TaskDag tasks={tasks} onSelect={setSelectedTaskId} />}
              {narrowTab === 'activity' && <EventTrace events={events} connected={connected} ended={ended} />}
              {narrowTab === 'chat' && <NarrativeChat runId={runId} events={events} active={active} />}
            </div>
          </section>
        ) : (
          <>
            {dagPane}
            {layoutMode === 'wide' ? (
              <DragHandle onMouseDown={startDrag('dag')} />
            ) : (
              <div className="w-px shrink-0 bg-slate-800/60" />
            )}
            {activityPane}
            {layoutMode === 'wide' && (
              <>
                <DragHandle onMouseDown={startDrag('chat')} />
                {chatPane}
              </>
            )}
            {/* medium：AI 交流折叠为抽屉（覆盖在主体上，不遮挡底部审批） */}
            {layoutMode === 'medium' && chatOpen && (
              <aside className="slide-in-right absolute inset-y-0 right-0 z-20 flex w-[368px] max-w-[80%] flex-col border-l border-slate-800 bg-slate-900 shadow-xl">
                <div className="flex h-9 shrink-0 items-center gap-2 border-b border-slate-800/60 px-3">
                  <span className="text-[13px] font-semibold text-slate-300">AI 解说 · 交流</span>
                  <button
                    onClick={() => setChatOpen(false)}
                    className="ml-auto text-xs text-slate-500 transition-colors hover:text-slate-300"
                  >
                    关闭 ✕
                  </button>
                </div>
                <div className="min-h-0 flex-1">
                  <NarrativeChat runId={runId} events={events} active={active} />
                </div>
              </aside>
            )}
          </>
        )}
      </main>

      {/* ================= 底部：人工审批 / 打断恢复（Contextual） ================= */}
      <ApprovalPanel runId={runId} payload={pendingApproval} onSubmitted={refreshAll} onViewDiff={toggleDiff} />

      {/* ================= 任务详情 / 产出物 / 审批留痕 ================= */}
      <TaskDetail task={selectedTask} onClose={() => setSelectedTaskId(null)} />
      <ArtifactViewer
        runId={runId}
        metas={artifactMetas}
        open={showArtifacts}
        onClose={() => setShowArtifacts(false)}
      />
      <ApprovalHistory runId={runId} open={showHistory} onClose={() => setShowHistory(false)} />

      {/* ================= Diff 抽屉（右上角） ================= */}
      {showDiff && (
        <aside className="slide-in-right fixed bottom-0 right-0 top-14 z-30 flex w-[760px] max-w-[92vw] flex-col border-l border-slate-800 bg-slate-900 shadow-xl">
          <div className="flex h-9 shrink-0 items-center gap-2 border-b border-slate-800/60 px-3">
            <span className="shrink-0 whitespace-nowrap text-[13px] font-semibold text-slate-300">代码变更 Diff</span>
            {diffData?.branch && (
              <span className="truncate rounded border border-slate-800 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                {diffData.branch}
              </span>
            )}
            <div className="ml-auto flex items-center gap-3 text-[11px]">
              <button
                onClick={() => setManualDiffTok((v) => v + 1)}
                className="text-slate-400 transition-colors hover:text-slate-200"
              >
                刷新
              </button>
              <button
                onClick={() => setShowDiff(false)}
                className="text-slate-500 transition-colors hover:text-slate-300"
              >
                关闭 ✕
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <DiffViewer diff={diffData?.diff ?? ''} loading={!run || active} />
          </div>
        </aside>
      )}

      {/* ================= 指标抽屉 ================= */}
      {showMetrics && (
        <aside className="slide-in-right fixed bottom-0 right-0 top-14 z-30 w-[360px] overflow-y-auto border-l border-slate-800 bg-slate-900 shadow-xl">
          <div className="flex h-9 items-center justify-between border-b border-slate-800/60 px-3">
            <span className="text-[13px] font-semibold text-slate-300">运行指标</span>
            <button onClick={() => setShowMetrics(false)} className="text-xs text-slate-500 hover:text-slate-300">
              关闭 ✕
            </button>
          </div>
          <MetricsPanel metrics={metrics} />
        </aside>
      )}
    </div>
  )
}
