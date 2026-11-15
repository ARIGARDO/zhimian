import { ArrowLeft, CheckCircle2, MessageCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TopicDetail } from '../api/types'
import { learningKeys, useTopic, useTopics, useUpdateProgress } from '../features/learning/queries'

export function TopicPage() {
  const { topicId } = useParams<{ topicId: string }>()
  const id = topicId ?? ''
  const current = useTopic(id)
  const topics = useTopics()
  return <>
    <div className="page-head compact"><div className="eyebrow">STRUCTURED LEARNING</div><h1>智能学习</h1><p>已选择专题 · 阅读位置自动保存，章节完成需手动确认。</p></div>
    <div className="row-between article-top"><Link className="app-button app-button-outline app-button-sm" to="/learn"><ArrowLeft size={15}/> 返回选择内容</Link>{current.data && <span className="pill teal">{current.data.category_label} / {current.data.title}</span>}</div>
    {current.isPending && <div className="surface-card empty-state">正在加载文章...</div>}
    {current.isError && <div className="alert error">无法加载专题。<button onClick={() => void current.refetch()}>重试</button><Link to="/learn">返回目录</Link></div>}
    {current.data && <div className="reader-layout">
      <aside className="surface-card lesson-sidebar"><h4>当前方向 · {current.data.category_label}</h4><nav aria-label="当前方向的章节">{topics.data?.filter(t => t.category === current.data!.category).map(t => <Link className={`lesson-link ${t.id===id?'active':''}`} to={`/learn/topics/${t.id}`} key={t.id}><span className="lesson-dot"/>{t.title}{t.completed && <CheckCircle2 size={14}/>}</Link>)}</nav><p>这里只列出当前方向的专题。其他课程请返回内容选择页。</p></aside>
      <TopicReader key={id} topic={current.data} />
      <aside className="surface-card assistant-aside"><div className="assistant-header"><strong>专题 AI 助手</strong><p>围绕当前专题提问，会话与其他专题分开保存。</p><Link className="app-button app-button-primary app-button-sm" to={`/learn/topics/${encodeURIComponent(id)}/chat`}><MessageCircle size={14}/> 进入专题问答</Link></div></aside>
    </div>}
  </>
}

function TopicReader({ topic }: { topic: TopicDetail }) {
  const [position, setPosition] = useState(topic.reading_position)
  const [positionError, setPositionError] = useState(false)
  const queryClient = useQueryClient()
  const articleRef = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastPosition = useRef(topic.reading_position)
  const progressMutation = useUpdateProgress(topic.id)
  const [completed, setCompleted] = useState(topic.completed)

  useEffect(() => {
    // Markdown 渲染后恢复文章内部滚动位置；刷新和专题切换都会重新加载数据库位置。
    const frame = requestAnimationFrame(() => {
      const el = articleRef.current
      if (el) el.scrollTop = (el.scrollHeight - el.clientHeight) * topic.reading_position
    })
    return () => cancelAnimationFrame(frame)
  }, [topic.id, topic.reading_position])

  useEffect(() => () => {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      // 路由离开时尽力刷新阅读位置；服务器记录是唯一可靠来源。
      void api.updateProgress(topic.id, { reading_position: lastPosition.current })
        .then(() => {
          void queryClient.invalidateQueries({ queryKey: learningKeys.topics })
          void queryClient.invalidateQueries({ queryKey: learningKeys.overview })
        }).catch(() => undefined)
    }
  }, [topic.id, queryClient])

  const handleScroll = () => {
    const el = articleRef.current
    if (!el) return
    const total = Math.max(0, el.scrollHeight - el.clientHeight)
    const next = total === 0 ? 0 : Math.max(0, Math.min(1, el.scrollTop / total))
    lastPosition.current = next
    setPosition(next)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null
      void api.updateProgress(topic.id, { reading_position: lastPosition.current })
        .then(() => {
          setPositionError(false)
          void queryClient.invalidateQueries({ queryKey: learningKeys.topics })
          void queryClient.invalidateQueries({ queryKey: learningKeys.overview })
        }).catch(() => setPositionError(true))
    }, 700)
  }
  const handleComplete = async () => {
    const previous = completed
    setCompleted(!previous)
    try { await progressMutation.mutateAsync({ completed: !previous }) }
    catch { setCompleted(previous) }
  }

  return <article className="surface-card article-card"><div className="article-scroll" ref={articleRef} onScroll={handleScroll}>
    <span className="pill teal">{topic.category_label}</span><h2>{topic.title}</h2><p className="article-summary">{topic.summary}</p>
    <div className="article-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{topic.content_md}</ReactMarkdown></div>
    <div style={{ height: 20 }}/>
  </div><footer className="article-footer"><div className="read-meta"><div>阅读位置 <strong>{Math.round(position*100)}%</strong> · <span className={`pill ${completed?'teal':'plain'}`}>{completed?'已完成':'未确认完成'}</span></div><div className="read-track"><span style={{ width: `${position*100}%` }}/></div></div>
    <button className={`app-button app-button-sm ${completed?'app-button-outline':'app-button-primary'}`} onClick={() => void handleComplete()} disabled={progressMutation.isPending}>{completed?'取消完成标记':'✓ 标记章节已完成'}</button>
    {(progressMutation.isError || positionError) && <small className="save-error">阅读位置或完成状态保存失败，请检查网络</small>}
  </footer></article>
}
