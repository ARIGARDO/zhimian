import { ArrowRight, BookOpen, Layers3, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTopics } from '../features/learning/queries'

type Filter = 'all' | 'python' | 'ai'
export function LearnCatalogPage() {
  const { data, isPending, isError, refetch } = useTopics()
  const [filter, setFilter] = useState<Filter>('all')
  const filtered = data?.filter(t => filter === 'all' || t.category === filter) ?? []
  return <>
    <div className="page-head"><div className="eyebrow">STRUCTURED LEARNING</div><h1>选择学习内容</h1><p>先选择技术方向或具体专题，再进入文章阅读。不必从左侧目录中逐个寻找。</p></div>
    <div className="section-title"><h2>学习方向</h2><span className="quiet-text">两大方向 · 自由选择</span></div>
    <div className="two-grid tracks">
      <button className={`surface-card track-card ${filter==='python'?'chosen':''}`} onClick={() => setFilter('python')}>
        <span className="track-icon"><BookOpen size={26}/></span><div><small>4 个入门专题</small><h2>Python 后端</h2><p>异步编程、接口设计、数据库和缓存</p><span className="text-link">查看专题 <ArrowRight size={15}/></span></div>
      </button>
      <button className={`surface-card track-card ${filter==='ai'?'chosen':''}`} onClick={() => setFilter('ai')}>
        <span className="track-icon"><Sparkles size={26}/></span><div><small>4 个入门专题</small><h2>AI 应用 / Agent</h2><p>RAG、重排序、Agent 与 LLM 评估</p><span className="text-link">查看专题 <ArrowRight size={15}/></span></div>
      </button>
    </div>
    <div className="section-title"><h2>选择具体专题</h2><div className="filter-buttons">{[
      ['all','全部'],['python','Python 后端'],['ai','AI / Agent'],
    ].map(([key,label]) => <button key={key} className={`filter ${filter===key?'selected':''}`} onClick={() => setFilter(key as Filter)}>{label}</button>)}</div></div>
    {isPending && <div className="surface-card empty-state">正在从 FastAPI 加载学习内容...</div>}
    {isError && <div className="alert error">学习目录加载失败。确认已运行数据库迁移与种子脚本。<button onClick={() => void refetch()}>重新加载</button></div>}
    {!isPending && !isError && <div className="three-grid">{filtered.map((topic) => <Link to={`/learn/topics/${topic.id}`} key={topic.id} className="surface-card topic-card">
      <div className="topic-card-top"><span className="topic-icon"><Layers3 size={19}/></span><div><strong>{topic.title}</strong><small>{topic.category_label}</small></div></div>
      <p>{topic.summary}</p>
      <div className="topic-card-bottom"><span className={`pill ${topic.completed?'teal':'plain'}`}>{topic.completed?'已完成':topic.reading_position>0?'继续学习':'开始学习'}</span><ArrowRight size={17}/></div>
    </Link>)}</div>}
  </>
}
