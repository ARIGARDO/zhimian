import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { interviewApi } from '../features/interview/api'
import { useOverview } from '../features/learning/queries'

export function GrowthPage() {
  const overview = useOverview()
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const interviews = useQuery({ queryKey: ['interviews', 'home'], queryFn: () => interviewApi.history('completed') })
  return <><div className="page-head"><div className="eyebrow">YOUR PROGRESS</div><h1>个人成长</h1><p>记录学习与练习。任务完成并不等同于掌握知识。</p></div>
    {(overview.isError || tasks.isError || interviews.isError) && <div className="alert error">部分数据加载失败，请稍后刷新。</div>}
    <div className="two-grid"><div className="surface-card interview-section"><h2>学习进度</h2><p>已开始 {overview.data?.started_topics ?? '—'} / {overview.data?.total_topics ?? '—'} 个专题，手动完成 {overview.data?.completed_topics ?? '—'} 个。</p><Link className="minor-link" to="/learn">继续学习</Link></div>
    <div className="surface-card interview-section"><h2>学习计划</h2><p>待完成或进行中 {tasks.data?.filter(t => t.status !== 'completed').length ?? '—'} 项，已完成 {tasks.data?.filter(t => t.status === 'completed').length ?? '—'} 项。</p><Link className="minor-link" to="/tasks">查看任务</Link></div></div>
    <section className="section"><h2>最近完成的面试</h2>{interviews.data?.length ? interviews.data.slice(0, 5).map(item => <p key={item.id}><Link className="minor-link" to={`/interviews/${item.id}/report`}>{item.preset?.name || '模拟面试'} · {new Date(item.created_at).toLocaleDateString('zh-CN')}</Link></p>) : <p>暂无已完成的面试。</p>}<Link className="minor-link" to="/interviews">查看全部面试记录</Link></section>
  </>
}
