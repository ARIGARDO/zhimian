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

export const api = {
  topics: () => request<TopicSummary[]>('/topics'),
  topic: (id: string) => request<TopicDetail>(`/topics/${encodeURIComponent(id)}`),
  overview: () => request<Overview>('/overview'),
  progress: (id: string) => request<ProgressRead>(`/progress/${encodeURIComponent(id)}`),
  updateProgress: (id: string, body: ProgressUpdate) =>
    request<ProgressRead>(`/progress/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
}
