import { ApiError } from '../../api/client'

export type Preset = { id: string; kind: 'bank' | 'role'; name: string; version: number }
export type Status = 'pending' | 'in_progress' | 'completed' | 'terminated' | 'interrupted'
export type Question = { id: string; main_number: number; depth: number; position: number; content: string; closed_at: string | null; answer: { id: string; kind: 'answer' | 'skip'; content: string; submitted_at: string } | null }
export type Interview = { id: string; status: Status; mode: 'practice' | 'formal'; preset: Preset; limit_type: 'time' | 'count'; main_limit: number | null; duration_seconds: number | null; started_at: string | null; deadline_at: string | null; ended_at: string | null; end_reason: string | null; main_count: number; valid_main_count: number; questions: Question[] }
export type History = Pick<Interview, 'id' | 'status' | 'mode' | 'preset' | 'ended_at'> & { created_at: string }
export type Review = { answer_id: string; review: string }
export type Report = { summary: string; items: Review[]; overall_score?: number }
export type Operation = { id?: string; status: 'running' | 'complete' | 'failed' | 'no_content'; error?: string; retryable?: boolean; result?: { feedback?: string; question_id?: string } & Partial<Report> }
export type ReportResponse = { status: 'ready' | 'not_requested' | 'no_content'; type: 'full' | 'partial'; result?: Report }
export type Pending = { key: string; path: string; body?: unknown; operationId?: string }

async function request<T>(path: string, init: RequestInit = {}, timeout = 20000): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(`/api/v1${path}`, { ...init, signal: controller.signal, headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
    if (!response.ok) {
      const data = await response.json().catch(() => null) as { detail?: unknown; end_reason?: string } | null
      throw new ApiError(response.status, typeof data?.detail === 'string' ? data.detail : data?.end_reason ? '面试已到期或结束，请刷新状态。' : `请求失败（${response.status}）`)
    }
    return await response.json() as T
  } finally { window.clearTimeout(timer) }
}
export const interviewApi = {
  presets: () => request<Preset[]>('/interview-presets'),
  questions: (id: string) => request<{ id: string; topic: string; version: number }[]>(`/interview-presets/${encodeURIComponent(id)}/questions`),
  detail: (id: string) => request<Interview>(`/interviews/${encodeURIComponent(id)}`),
  history: (status: string) => request<History[]>(`/interviews?status=${status}&limit=100`),
  report: (id: string) => request<ReportResponse>(`/interviews/${encodeURIComponent(id)}/ai/report`),
  operation: (id: string, op: string) => request<Operation>(`/interviews/${encodeURIComponent(id)}/ai/operations/${encodeURIComponent(op)}`),
  post: <T>(pending: Pending) => request<T>(pending.path, { method: 'POST', headers: { 'Idempotency-Key': pending.key }, ...(pending.body === undefined ? {} : { body: JSON.stringify(pending.body) }) }, 15000),
}

// 未确认的写请求在当前浏览器标签页保留原键和原请求体，避免网络中断后重复写入。
export function loadPending(slot: string): Pending | null {
  try { const value = sessionStorage.getItem(`interview:${slot}`); return value ? JSON.parse(value) as Pending : null } catch { return null }
}
export function savePending(slot: string, value: Pending | null) {
  if (value) sessionStorage.setItem(`interview:${slot}`, JSON.stringify(value))
  else sessionStorage.removeItem(`interview:${slot}`)
}
export function newPending(path: string, body?: unknown): Pending {
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes)
  return { key: Array.from(bytes, b => b.toString(16).padStart(2, '0')).join(''), path, body }
}
