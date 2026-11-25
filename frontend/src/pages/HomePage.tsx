import type { ReactNode } from 'react'
import { ArrowRight, BookOpen, CheckCircle2, Clock, Database, MessageCircle, Mic } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useOverview, useTopics } from '../features/learning/queries'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { interviewApi } from '../features/interview/api'

export function HomePage() {
  const overview = useOverview()
  const topics = useTopics()
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const interviews = useQuery({ queryKey: ['interviews', 'home'], queryFn: () => interviewApi.history('completed') })
  const first = topics.data?.find((topic) => !topic.completed) ?? topics.data?.[0]
  return <>
    <div className="hero">
      <div><div className="eyebrow hero-eyebrow">YOUR NEXT STEP</div><h1>边学习，边练习，<br/>让每一次面试都有收获。</h1>
        <p>从结构化知识到真实场景的技术表达，再从复盘回到针对性学习。先把学习基础跑通，逐步接入 AI 能力。</p>
        <div className="hero-actions"><Link className="app-button app-button-secondary" to="/learn"><BookOpen size={16}/>智能学习</Link><Link className="app-button hero-secondary" to="/interviews/new"><Mic size={16}/>模拟面试</Link></div>
      </div><div className="hero-monogram" aria-hidden="true">知</div>
    </div>
    <section className="section"><div className="section-title"><h2>你的学习概览</h2><Link className="minor-link" to="/growth">查看我的成长 <ArrowRight size={15}/></Link></div>
      <div className="metrics-grid">
        <Metric icon={<BookOpen/>} label="已完成章节" value={overview.data ? String(overview.data.completed_topics) : '—'} note="手动标记完成" />
        <Metric icon={<Mic/>} label="已完成面试" value={interviews.data ? String(interviews.data.length) : '—'} note="最近记录（最多 100 场）" />
        <Metric icon={<CheckCircle2/>} label="待完成任务" value={tasks.data ? String(tasks.data.filter(task => task.status !== 'completed').length) : '—'} note="由你确认加入" />
        <Metric icon={<MessageCircle/>} label="学习进度" value={overview.data ? `${overview.data.started_topics} / ${overview.data.total_topics}` : '—'} note="已开始 / 全部专题" />
      </div>
      {(overview.isError || topics.isError) && <div className="alert error">无法连接学习 API。请检查 FastAPI 与 PostgreSQL 是否已启动、迁移并导入专题。<button onClick={() => { void overview.refetch(); void topics.refetch() }}>重试</button></div>}
    </section>
    <section className="section"><div className="section-title"><h2>从这里继续</h2><span className="quiet-text">可以立即开始的内容</span></div>
      <div className="two-grid">
        <div className="surface-card continue-card"><span className="pill teal">继续学习</span><BookOpen className="card-corner-icon" size={20}/><h3>{first?.title ?? '选择一个学习专题'}</h3><p>{first?.summary ?? '进入学习目录，选择你想学习的课程。'}</p><Link className="app-button app-button-primary app-button-sm" to={first ? `/learn/topics/${first.id}` : '/learn'}>开始阅读 <ArrowRight size={15}/></Link></div>
        <div className="surface-card continue-card"><span className="pill blue">下一步</span><Mic className="card-corner-icon" size={20}/><h3>开始第一次模拟面试</h3><p>选择可用题库，进行技术问答并查看面试复盘。</p><Link className="app-button app-button-outline app-button-sm" to="/interviews/new">配置面试 <ArrowRight size={15}/></Link></div>
      </div>
    </section>
    <section className="section"><div className="section-title"><h2>最小完整闭环</h2><span className="quiet-text">V4.3 产品基线</span></div>
      <div className="flow-grid">{[
        ['01','学习','浏览结构化专题'],['02','问答','结合知识库理解问题'],['03','模拟面试','真实场景表达与追问'],['04','逐题复盘','找出需要加强的知识'],['05','继续学习','确认任务，回到专题'],
      ].map(([step, title, text]) => <div className="flow-tile" key={step}><b>{step}</b><strong>{title}</strong><span>{text}</span></div>)}</div>
    </section>
    <div className="alert info"><Database size={17}/><span><strong>真实 M1 工程：</strong>课程、文章和阅读进度来自 FastAPI + PostgreSQL。AI 问答和模拟面试已接入服务端；面试题库需先完成内容审核。</span><Clock size={16}/></div>
  </>
}
function Metric({ icon, label, value, note }: { icon: ReactNode; label: string; value: string; note: string }) {
  return <div className="surface-card metric"><div className="metric-head"><span>{label}</span>{icon}</div><strong>{value}</strong><small>{note}</small></div>
}
