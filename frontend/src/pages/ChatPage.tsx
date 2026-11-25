import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Conversation = { id: string; title: string; topic_id: string | null }
type Source = { topic_id: string; title: string; section?: string; excerpt: string }
type Message = { id: string; role: string; content: string; status: string; sources?: Source[] | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { ...init, headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `请求失败（${res.status}）`)
  }
  return res.status === 204 ? undefined as T : res.json() as Promise<T>
}

export function ChatPage({ topicId }: { topicId?: string }) {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const scope = topicId ? `?topic_id=${encodeURIComponent(topicId)}` : ''
  const base = topicId ? `/learn/topics/${encodeURIComponent(topicId)}/chat` : '/assistant'
  const [history, setHistory] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const activeId = useRef<string | null>(null)
  const refresh = () => request<Conversation[]>(`/conversations${topicId ? `?topic_id=${encodeURIComponent(topicId)}` : ''}`).then(setHistory)
  useEffect(() => {
    if (activeId.current && activeId.current !== conversationId) controller.current?.abort()
    let live = true
    void request<Conversation[]>(`/conversations${topicId ? `?topic_id=${encodeURIComponent(topicId)}` : ''}`).then(async list => {
      if (!live) return
      setHistory(list)
      if (!conversationId) { setMessages([]); setError(''); return }
      if (!list.some(c => c.id === conversationId)) { setMessages([]); setError('会话不存在或不属于当前范围'); return }
      if (activeId.current === conversationId) return
      const data = await request<Message[]>(`/conversations/${encodeURIComponent(conversationId)}/messages${scope}`)
      if (live) { setMessages(data); setError('') }
    }).catch(e => { if (live) setError(e instanceof Error ? e.message : '加载失败') })
    return () => { live = false }
  }, [topicId, conversationId])
  useEffect(() => () => controller.current?.abort(), [topicId])

  const send = async () => {
    const content = input.trim()
    if (!content || busy) return
    setBusy(true); setError('')
    let id = conversationId
    let replyId: string = crypto.randomUUID()
    let userId: string = crypto.randomUUID()
    let finished = false
    let started = false
    const abort = new AbortController(); controller.current = abort
    try {
      if (!id) {
        const created = await request<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ title: content.slice(0, 100), topic_id: topicId ?? null }), signal: abort.signal })
        id = created.id
        activeId.current = id
        navigate(`${base}/${encodeURIComponent(id)}`, { replace: true })
        void refresh().catch(() => undefined)
      } else activeId.current = id
      setInput('')
      setMessages(prev => [...prev, { id: userId, role: 'user', content, status: 'complete' }, { id: replyId, role: 'assistant', content: '', status: 'streaming' }])
      const res = await fetch(`/api/v1/conversations/${encodeURIComponent(id)}/messages/stream${scope}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }), signal: abort.signal })
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null) as { detail?: string } | null
        throw new Error(body?.detail || `发送失败（${res.status}）`)
      }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let match: RegExpMatchArray | null
        while ((match = buffer.match(/\r?\n\r?\n/))) {
          const boundary = match.index!; const frame = buffer.slice(0, boundary).replace(/\r\n/g, '\n'); buffer = buffer.slice(boundary + match[0].length)
          const kind = frame.match(/^event: ?(.+)$/m)?.[1]; const data = frame.match(/^data: ?(.+)$/m)?.[1]
          if (!data) continue
          const payload = JSON.parse(data) as { id?: string; user_id?: string; content?: string; message?: string; sources?: Source[] }
          if (kind === 'start' && payload.id && payload.user_id) {
            started = true
            const previousReply = replyId; const previousUser = userId
            replyId = payload.id; userId = payload.user_id
            const actualReply = replyId; const actualUser = userId
            setMessages(prev => prev.map(m => m.id === previousReply ? { ...m, id: actualReply, sources: payload.sources } : m.id === previousUser ? { ...m, id: actualUser } : m))
          }
          if (kind === 'delta') { const target = replyId; setMessages(prev => prev.map(m => m.id === target ? { ...m, content: m.content + (payload.content ?? '') } : m)) }
          if (kind === 'done') { finished = true; const target = replyId; setMessages(prev => prev.map(m => m.id === target ? { ...m, status: 'complete' } : m)) }
          if (kind === 'error') { finished = true; const target = replyId; setMessages(prev => prev.map(m => m.id === target ? { ...m, status: 'error' } : m)); setError(payload.message ?? '模型请求失败') }
        }
      }
      if (!finished) throw new Error('连接中断，请刷新查看已保存的回复')
    } catch (e) {
      const cancelled = e instanceof DOMException && e.name === 'AbortError'
      const target = replyId; const pendingUser = userId
      setMessages(prev => started ? prev.map(m => m.id === target ? { ...m, status: cancelled ? 'cancelled' : 'error' } : m) : prev.filter(m => m.id !== target && m.id !== pendingUser))
      if (!cancelled) setError(e instanceof Error ? e.message : '发送失败')
    } finally {
      controller.current = null; activeId.current = null; setBusy(false)
      void refresh().catch(() => undefined)
    }
  }
  const remove = async (id: string) => {
    try { await request<void>(`/conversations/${encodeURIComponent(id)}${scope}`, { method: 'DELETE' }); if (conversationId === id) navigate(base); await refresh() }
    catch (e) { setError(String(e)) }
  }
  return <div className="chat-page"><div className="page-head"><div className="eyebrow">AI ASSISTANT</div><h1>{topicId ? '专题 AI 助手' : 'AI 问答助手'}</h1><p>{topicId ? '围绕当前专题提问，历史记录按专题保存。' : '发送第一条消息后创建会话。'}</p></div>
    <div className="chat-layout"><aside className="surface-card chat-history"><button className="app-button app-button-outline" disabled={busy} onClick={() => navigate(base)}>＋ 新会话</button><h3>历史记录</h3>{history.map(c => <div className="chat-history-row" key={c.id}><button disabled={busy} onClick={() => navigate(`${base}/${encodeURIComponent(c.id)}`)} aria-current={conversationId === c.id}>{c.title}</button><button disabled={busy} aria-label={`删除 ${c.title}`} onClick={() => { if (window.confirm('确定删除此会话及其消息？')) void remove(c.id) }}>删除</button></div>)}</aside>
      <section className="surface-card chat-main" aria-label="聊天内容"><div className="chat-messages">{messages.length === 0 && <p>输入问题，开始对话。</p>}{messages.map(m => <div key={m.id} className={`chat-message ${m.role}`}><strong>{m.role === 'user' ? '你' : 'AI 助手'}</strong><div className="article-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>{!!m.sources?.length && <details><summary>本次检索到的知识资料（{m.sources.length}）</summary>{m.sources.map((source, index) => <div key={`${source.topic_id}-${index}`}><Link className="minor-link" to={`/learn/topics/${encodeURIComponent(source.topic_id)}${source.section ? `?section=${encodeURIComponent(source.section)}` : ''}`}>{source.title}{source.section ? ` · ${source.section}` : ''}</Link><p>{source.excerpt}</p></div>)}</details>}{m.role === 'assistant' && Array.isArray(m.sources) && m.sources.length === 0 && <small>未检索到相关专题资料，本次回答没有知识来源。</small>}{['cancelled', 'error', 'streaming'].includes(m.status) && <small>{m.status === 'cancelled' ? '已停止' : m.status === 'error' ? '生成失败' : '生成中'}</small>}</div>)}</div>
        {error && <div className="alert error" role="alert">{error}</div>}<div className="chat-compose"><textarea aria-label="输入问题" value={input} onChange={e => setInput(e.target.value)} placeholder="输入你的问题" maxLength={12000}/><div>{busy ? <button className="app-button app-button-outline" onClick={() => controller.current?.abort()}>停止生成</button> : <button className="app-button app-button-primary" disabled={!input.trim()} onClick={() => void send()}>发送</button>}</div></div></section></div></div>
}
