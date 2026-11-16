import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { interviewApi, loadPending, newPending, savePending } from './api'
import type { Operation, Pending } from './api'

export function errorText(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError' ? '请求超时或连接中断。服务端可能仍在处理，请用原请求恢复。' : error instanceof Error ? error.message : '请求失败，请重试。'
}

export function useAction(slot: string, interviewId?: string) {
  const cache = useQueryClient()
  const [pending, setPending] = useState<Pending | null>(() => loadPending(slot))
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Operation | null>(null)
  const update = (p: Pending | null) => { savePending(slot, p); setPending(p) }
  const operation = useQuery({
    queryKey: ['interview-operation', interviewId, pending?.operationId],
    queryFn: () => interviewApi.operation(interviewId!, pending!.operationId!),
    enabled: !!interviewId && !!pending?.operationId,
    refetchInterval: query => query.state.data?.status === 'running' ? 3000 : false,
    retry: 1,
  })
  const send = async <T,>(path?: string, body?: unknown, ai = false): Promise<T | null> => {
    if (busyRef.current) return null
    const request = pending ?? newPending(path!, body)
    if (pending && path && (pending.path !== path || JSON.stringify(pending.body) !== JSON.stringify(body))) {
      setError('存在尚未确认的请求，请先恢复原请求。'); return null
    }
    busyRef.current = true
    update(request); setBusy(true); setError('')
    try {
      const response = await interviewApi.post<T & Partial<Operation>>(request)
      if (ai && response.status) {
        const op = response as Operation
        setResult(op)
        if (op.id) {
          update({ ...request, operationId: op.id })
          await cache.invalidateQueries({ queryKey: ['interview-operation', interviewId, op.id] })
        }
        if (op.status === 'no_content') update(null)
      } else update(null)
      await cache.invalidateQueries({ queryKey: ['interviews'] })
      return response
    } catch (e) {
      setError(errorText(e))
      // 确定性的客户端拒绝不会写入；超时、断线和服务端错误必须保留原请求。
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) update(null)
      await cache.invalidateQueries({ queryKey: ['interviews'] })
      return null
    } finally { busyRef.current = false; setBusy(false) }
  }
  return { pending, busy, error, result: operation.data ?? result, operationError: operation.isError, send, refreshOperation: operation.refetch }
}
