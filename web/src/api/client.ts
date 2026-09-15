/** REST 客户端与 API 基址解析。 */
import type {
  ApprovalPayload,
  ArtifactData,
  ArtifactMeta,
  GuidanceItem,
  Metrics,
  Project,
  ProjectDetail,
  RunEvent,
  RunInfo,
  RunStateResp,
  TaskItem,
} from './types'

/** 开发模式（Vite dev server :5173）直连后端；生产模式同源（FastAPI 托管）。 */
export const API_BASE: string = (() => {
  const env = (import.meta.env.VITE_API_BASE as string | undefined)?.trim()
  if (env) return env.replace(/\/$/, '')
  if (typeof window !== 'undefined' && window.location.port === '5173') {
    return 'http://127.0.0.1:8000'
  }
  return ''
})()

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* 忽略解析失败 */
    }
    throw new ApiError(resp.status, detail)
  }
  return (await resp.json()) as T
}

// =========================================================
// REST API
// =========================================================

export const api = {
  health: () => request<{ status: string; app: string }>('/health'),

  listProjects: () => request<{ projects: Project[] }>('/projects'),

  getProject: (id: string) => request<ProjectDetail>(`/projects/${id}`),

  createProject: (payload: {
    name: string
    repo_path: string
    default_branch?: string
    init_if_needed?: boolean
  }) => request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),

  createRun: (projectId: string, req: string, approvalMode = 'auto', mode = 'auto') =>
    request<{ run: RunInfo }>(`/projects/${projectId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ request: req, approval_mode: approvalMode, mode }),
    }),

  getRun: (runId: string) => request<RunInfo>(`/runs/${runId}`),

  getRunState: (runId: string) => request<RunStateResp>(`/runs/${runId}/state`),

  getTasks: (runId: string) => request<{ tasks: TaskItem[] }>(`/runs/${runId}/tasks`),

  getDiff: (runId: string, statOnly = false) =>
    request<{ diff: string; branch: string; workspace: string }>(
      `/runs/${runId}/diff?stat_only=${statOnly}`,
    ),

  getMetrics: (runId: string) => request<Metrics>(`/runs/${runId}/metrics`),

  approve: (runId: string, decision: string, note = '') =>
    request<{ accepted: boolean; decision: string }>(`/runs/${runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ decision, note, by: 'ui' }),
    }),

  /** 运行中追加需求（不打断执行，Agent 下一步自动采纳）。 */
  sendGuidance: (runId: string, text: string) =>
    request<{ accepted: boolean; guidance: GuidanceItem }>(`/runs/${runId}/guidance`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  listGuidance: (runId: string) => request<{ guidance: GuidanceItem[] }>(`/runs/${runId}/guidance`),

  /** 切换运行级审批模式：auto | interactive。 */
  setApprovalMode: (runId: string, mode: string) =>
    request<{ accepted: boolean; approval_mode: string }>(`/runs/${runId}/approval_mode`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    }),

  /** 终止运行（人工取消）。 */
  cancelRun: (runId: string) =>
    request<{ accepted: boolean; run_id: string }>(`/runs/${runId}/cancel`, { method: 'POST' }),

  /** 人工打断：下一个安全点暂停，可在恢复时补充新需求（resume/approve 携带 note）。 */
  requestPause: (runId: string) =>
    request<{ accepted: boolean; run_id: string; note: string }>(`/runs/${runId}/pause`, {
      method: 'POST',
    }),

  resume: (runId: string, resume: Record<string, unknown>) =>
    request<{ resumed: boolean }>(`/runs/${runId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ resume }),
    }),

  listApprovals: (runId: string) =>
    request<{ approvals: ApprovalRecord[] }>(`/runs/${runId}/approvals`),

  listArtifacts: (runId: string) =>
    request<{ artifacts: ArtifactMeta[] }>(`/runs/${runId}/artifacts`),

  getArtifact: (runId: string, name: string) =>
    request<ArtifactData>(`/runs/${runId}/artifacts/${name}`),
}

export interface ApprovalRecord {
  id: string
  tool: string
  arguments: Record<string, unknown>
  risk_level: string
  reason: string
  status: string
  /** 审批范围：once（仅本次）| always（本运行内免问） */
  scope: string
  consumed: boolean
  decided_by: string
  note: string
  requested_at: string | null
  decided_at: string | null
}

// SSE 帧中的 data 字段
export type SSEFrame = RunEvent

export type { ApprovalPayload, GuidanceItem, Metrics, RunEvent, TaskItem }
