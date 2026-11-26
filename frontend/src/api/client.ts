import type { Overview, ProgressRead, ProgressUpdate, TopicDetail, TopicSummary } from './types'

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message) }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null
    const detail = error?.detail
    throw new ApiError(response.status, typeof detail === 'string' ? detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export type ModelConfiguration = { chat: 'configured' | 'missing' | 'invalid_url'; embedding: 'configured' | 'missing' | 'invalid_url'; embedding_dimensions: number; embedding_provider: string }

export type LearningTask = { id: string; interview_id: string; answer_id: string; topic_id: string; topic_title: string; status: 'todo' | 'in_progress' | 'completed'; created_at: string }

export const api = {
  modelConfiguration: () => request<ModelConfiguration>('/model/configuration'),
  tasks: () => request<LearningTask[]>('/tasks'),
  createTask: (body: { interview_id: string; answer_id: string; topic_id: string }) => request<LearningTask>('/tasks', { method: 'POST', body: JSON.stringify(body) }),
  updateTask: (id: string, status: LearningTask['status']) => request<LearningTask>(`/tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  topics: () => request<TopicSummary[]>('/topics'),
  topic: (id: string) => request<TopicDetail>(`/topics/${encodeURIComponent(id)}`),
  overview: () => request<Overview>('/overview'),
  progress: (id: string) => request<ProgressRead>(`/progress/${encodeURIComponent(id)}`),
  updateProgress: (id: string, body: ProgressUpdate) =>
    request<ProgressRead>(`/progress/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
}
