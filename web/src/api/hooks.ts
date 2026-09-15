/** 数据获取 hooks：REST 轮询 + SSE 事件流。 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, API_BASE, type ApprovalRecord } from './client'
import {
  EVENT_TYPES,
  isTerminal,
  type ArtifactData,
  type ArtifactMeta,
  type Project,
  type ProjectDetail,
  type RunEvent,
  type RunInfo,
  type RunStateResp,
  type TaskItem,
} from './types'

/**
 * 通用轮询 hook：
 * - key 变化时立即重新拉取并重置循环
 * - stopWhen 返回 true 时停止轮询（如运行到达终态）
 */
export function usePolling<T>(
  fetcher: (() => Promise<T>) | null,
  key: string,
  intervalMs = 3000,
  stopWhen?: (data: T) => boolean,
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fetcherRef = useRef(fetcher)
  const stopWhenRef = useRef(stopWhen)
  fetcherRef.current = fetcher
  stopWhenRef.current = stopWhen

  useEffect(() => {
    if (!fetcherRef.current) return
    let stopped = false
    let timer: number | undefined
    const doTick = async () => {
      const f = fetcherRef.current
      if (!f || stopped) return
      try {
        const d = await f()
        setData(d)
        setError(null)
        if (stopWhenRef.current?.(d)) {
          stopped = true
          if (timer !== undefined) window.clearInterval(timer)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
    void doTick()
    timer = window.setInterval(() => void doTick(), intervalMs)
    return () => {
      stopped = true
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [key, intervalMs])

  const refresh = useCallback(async () => {
    const f = fetcherRef.current
    if (!f) return
    try {
      setData(await f())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  return { data, error, refresh }
}

// =========================================================
// 领域 hooks
// =========================================================

export function useProjects() {
  return usePolling<{ projects: Project[] }>(() => api.listProjects(), 'projects', 8000)
}

export function useProject(projectId?: string) {
  return usePolling<ProjectDetail>(
    projectId ? () => api.getProject(projectId) : null,
    `project:${projectId}`,
    5000,
  )
}

export function useRun(runId?: string) {
  return usePolling<RunInfo>(
    runId ? () => api.getRun(runId) : null,
    `run:${runId}`,
    2500,
    (data) => isTerminal(data.status),
  )
}

export function useTasks(runId?: string, active = true) {
  return usePolling<{ tasks: TaskItem[] }>(
    runId && active ? () => api.getTasks(runId) : null,
    `tasks:${runId}:${active}`,
    3000,
  )
}

export function useRunState(runId?: string, active = true) {
  return usePolling<RunStateResp>(
    runId && active ? () => api.getRunState(runId) : null,
    `state:${runId}:${active}`,
    4000,
  )
}

export function useDiff(runId?: string, refreshToken = 0) {
  return usePolling<{ diff: string; branch: string; workspace: string }>(
    runId ? () => api.getDiff(runId) : null,
    `diff:${runId}:${refreshToken}`,
    30000,
  )
}

/** 产出物元信息列表（运行中轮询，运行结束后由 key 变化停止不必要刷新）。 */
export function useArtifacts(runId?: string, active = true) {
  return usePolling<{ artifacts: ArtifactMeta[] }>(
    runId && active ? () => api.listArtifacts(runId) : null,
    `artifacts:${runId}:${active}`,
    5000,
  )
}

/** 单个产出物内容（运行中定期刷新，跟踪修复循环中的报告更新）。 */
export function useArtifact(runId?: string, name?: string | null, active = true) {
  return usePolling<ArtifactData>(
    runId && name && active ? () => api.getArtifact(runId, name) : null,
    `artifact:${runId}:${name}:${active}`,
    6000,
  )
}

/** 审批留痕记录（打开抽屉时轮询）。 */
export function useApprovals(runId?: string, active = true) {
  return usePolling<{ approvals: ApprovalRecord[] }>(
    runId && active ? () => api.listApprovals(runId) : null,
    `approvals:${runId}:${active}`,
    6000,
  )
}

// =========================================================
// SSE 事件流
// =========================================================

function parseSSEText(text: string): RunEvent[] {
  const frames: RunEvent[] = []
  for (const line of text.split('\n')) {
    if (!line.startsWith('data: ')) continue
    try {
      frames.push(JSON.parse(line.slice(6)) as RunEvent)
    } catch {
      /* 忽略坏帧 */
    }
  }
  return frames
}

export function useRunEvents(runId?: string, runStatus?: string) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [ended, setEnded] = useState(false)
  const lastSeqRef = useRef(-1)
  const terminalRef = useRef(false)
  terminalRef.current = !!runStatus && isTerminal(runStatus)

  const mergeFrames = useCallback((frames: RunEvent[]) => {
    if (!frames.length) return
    setEvents((prev) => {
      const have = new Set(prev.map((e) => e.seq))
      const add = frames.filter((f) => !have.has(f.seq) && f.seq > lastSeqRef.current)
      if (!add.length) return prev
      const merged = [...prev, ...add].sort((a, b) => a.seq - b.seq)
      lastSeqRef.current = merged[merged.length - 1].seq
      return merged
    })
  }, [])

  useEffect(() => {
    if (!runId) return
    setEvents([])
    setEnded(false)
    lastSeqRef.current = -1
    let closed = false
    let es: EventSource | null = null
    let retryTimer: number | undefined

    const drain = async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/runs/${runId}/events?follow=false&after_seq=${lastSeqRef.current}`,
        )
        mergeFrames(parseSSEText(await resp.text()))
      } catch {
        /* 忽略 */
      }
    }

    const connect = () => {
      if (closed) return
      es = new EventSource(`${API_BASE}/runs/${runId}/events?after_seq=${lastSeqRef.current}`)
      es.onopen = () => setConnected(true)
      const handle = (ev: MessageEvent) => {
        try {
          mergeFrames([JSON.parse(ev.data) as RunEvent])
        } catch {
          /* 忽略坏帧 */
        }
      }
      for (const t of EVENT_TYPES) es.addEventListener(t, handle as EventListener)
      es.onerror = () => {
        setConnected(false)
        es?.close()
        if (closed) return
        if (terminalRef.current) {
          // 运行已结束：服务端关闭流，做最后一次补位拉取后标记结束
          void drain().finally(() => setEnded(true))
          return
        }
        retryTimer = window.setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      closed = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      es?.close()
    }
  }, [runId, mergeFrames])

  return { events, connected, ended }
}
