/** 与后端 API 对应的类型定义（app/api/*.py、app/schemas/*.py）。 */

export interface Project {
  id: string
  name: string
  repo_path: string
  default_branch: string
}

export interface RunBrief {
  id: string
  status: string
  created_at: string | null
}

export interface ProjectDetail {
  project: Project
  runs: RunBrief[]
}

export interface RunInfo {
  id: string
  project_id: string
  request: string
  status: string
  current_agent: string
  /** 请求模式：auto（LLM 意图判定）| query（只读问答）| develop（开发闭环） */
  mode: string
  /** 审批模式：auto（仅高风险）| interactive（关键操作逐步确认） */
  approval_mode: string
  branch: string
  workspace_path: string
  error: string | null
  metrics: Metrics
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
  project: { id: string; name: string } | null
}

export interface RunEvent {
  id: string
  run_id: string
  seq: number
  type: string
  agent: string
  message: string
  data: Record<string, unknown>
  ts: number
}

export interface TaskItem {
  id: string
  title: string
  description: string
  dependencies: string[]
  status: string
  assigned_agent: string
  priority: string
  acceptance_criteria: string[]
  attempts: number
  result_summary: string | null
  error: string | null
}

/** 运行产出物（GET /runs/{id}/artifacts）。 */
export interface ArtifactMeta {
  name: string
  title: string
  agent: string
  exists: boolean
  size: number
  modified_at: string | null
}

export interface ArtifactData {
  name: string
  data: Record<string, unknown>
}

export interface ReviewIssue {
  severity?: string
  file?: string
  problem?: string
  suggestion?: string
}

export interface TestFailure {
  test?: string
  message?: string
  file?: string
}

export interface ApprovalPayload {
  type?: string
  reason?: string
  /** 每次挂起唯一（用于前端区分多次审批请求：同一工具再次请求时复位面板状态） */
  approval_id?: string
  needs_human?: boolean
  summary?: string
  tasks_total?: number
  tasks_completed?: number
  tests_passed?: boolean
  review_approved?: boolean
  changed_files?: string[]
  options?: string[]
  tool?: string
  arguments?: Record<string, unknown>
  /** 当前运行审批模式（interactive 时 options 含 approve_once/approve_always） */
  approval_mode?: string
  /** 超限诊断：各环节重试次数与上限（needs_human 时展示） */
  retries?: Record<string, number>
  max_code_retry?: number
  review_issues?: ReviewIssue[]
  test_failures?: TestFailure[]
  blockers?: string[]
  current_agent?: string
  [key: string]: unknown
}

/** 只读问答结果（answer_ready 事件 / answer 工件）。 */
export interface AnswerResult {
  markdown: string
  key_points?: string[]
  files_referenced?: string[]
}

export interface RunStateResp {
  state: Record<string, unknown>
  next: string[]
  pending_approval: ApprovalPayload | null
}

/** 运行中人工补充要求（POST/GET /runs/{id}/guidance）。 */
export interface GuidanceItem {
  id: number
  text: string
  source: string
  status?: string
  created_at: string | null
  consumed_at?: string | null
}

export type Metrics = Record<string, number | string | boolean | null | undefined>

/** SSE 事件类型（与 app/schemas/events.py EventType 一致）。 */
export const EVENT_TYPES = [
  'run_started',
  'intent_decided',
  'supervisor_analyzing',
  'supervisor_decision',
  'requirements_ready',
  'architecture_ready',
  'tasks_generated',
  'answer_ready',
  'task_ready',
  'task_started',
  'task_completed',
  'task_failed',
  'agent_started',
  'agent_finished',
  'plan_updated',
  'tool_call',
  'tool_result',
  'test_started',
  'test_result',
  'validation_result',
  'repairing',
  'review_started',
  'review_result',
  'diff_ready',
  'approval_required',
  'approval_received',
  'pause_requested',
  'pause_resumed',
  'guidance_received',
  'guidance_applied',
  'commit_done',
  'run_finished',
  'run_failed',
  'run_cancelled',
  'error',
  'log',
] as const

export const TERMINAL_STATUSES = ['completed', 'failed', 'rejected', 'cancelled']

export const isTerminal = (status: string | undefined | null) =>
  !!status && TERMINAL_STATUSES.includes(status)
