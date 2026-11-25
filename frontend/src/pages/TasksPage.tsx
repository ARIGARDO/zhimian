import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type LearningTask } from '../api/client'

const labels = { todo: '待完成', in_progress: '进行中', completed: '已完成' }

export function TasksPage() {
  const client = useQueryClient()
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const update = useMutation({ mutationFn: ({ id, status }: { id: string; status: LearningTask['status'] }) => api.updateTask(id, status), onSuccess: () => client.invalidateQueries({ queryKey: ['tasks'] }) })
  return <><div className="page-head"><div className="eyebrow">LEARNING PLAN</div><h1>学习任务</h1><p>从面试复盘中选择专题并确认加入计划。完成任务不会自动标记知识已掌握。</p></div>
    {tasks.isPending && <div className="surface-card empty-state">正在加载学习任务...</div>}
    {(tasks.isError || update.isError) && <div className="alert error">任务操作失败，请稍后重试。</div>}
    {tasks.data?.length === 0 && <div className="surface-card empty-state">暂无任务。查看面试复盘，选择需要继续学习的专题。</div>}
    <div className="interview-stack">{tasks.data?.map(task => <div className="surface-card interview-section" key={task.id}>
      <span className="pill teal">{labels[task.status]}</span><h3>{task.topic_title}</h3>
      <p>来源：<Link className="minor-link" to={`/interviews/${task.interview_id}/report`}>面试复盘</Link></p>
      <label>任务状态 <select value={task.status} disabled={update.isPending} onChange={e => update.mutate({ id: task.id, status: e.target.value as LearningTask['status'] })}><option value="todo">待完成</option><option value="in_progress">进行中</option><option value="completed">已完成</option></select></label>{' '}
      <Link className="app-button app-button-outline app-button-sm" to={`/learn/topics/${task.topic_id}`}>打开专题</Link>
    </div>)}</div>
  </>
}
