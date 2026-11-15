import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { ProgressUpdate } from '../../api/types'

export const learningKeys = {
  topics: ['topics'] as const,
  topic: (id: string) => ['topics', id] as const,
  overview: ['overview'] as const,
}

export function useTopics() {
  return useQuery({ queryKey: learningKeys.topics, queryFn: api.topics, staleTime: 60_000 })
}
export function useTopic(id: string) {
  return useQuery({ queryKey: learningKeys.topic(id), queryFn: () => api.topic(id), staleTime: 60_000 })
}
export function useOverview() {
  return useQuery({ queryKey: learningKeys.overview, queryFn: api.overview, staleTime: 30_000 })
}
export function useUpdateProgress(topicId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProgressUpdate) => api.updateProgress(topicId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: learningKeys.topic(topicId) })
      queryClient.invalidateQueries({ queryKey: learningKeys.topics })
      queryClient.invalidateQueries({ queryKey: learningKeys.overview })
    },
  })
}
