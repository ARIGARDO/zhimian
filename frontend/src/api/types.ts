// M1 约定由 API Schema 同步；后续用已确定的 Hey API 生成替换此手写类型。
export type TopicSummary = {
  id: string
  category: 'python' | 'ai'
  category_label: string
  title: string
  summary: string
  sort_order: number
  completed: boolean
  reading_position: number
}
export type TopicDetail = TopicSummary & { content_md: string }
export type ProgressRead = {
  topic_id: string
  reading_position: number
  completed: boolean
  updated_at: string | null
}
export type ProgressUpdate = { reading_position?: number; completed?: boolean }
export type Overview = {
  total_topics: number
  completed_topics: number
  started_topics: number
  next_topic_id: string | null
  next_topic_title: string | null
}
