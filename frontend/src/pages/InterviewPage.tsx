import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useTopics } from '../features/learning/queries'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, Clock3, FileText, Mic, Sparkles } from 'lucide-react'
import { interviewApi } from '../features/interview/api'
import type { Interview, Operation, Question, Report } from '../features/interview/api'
import { errorText, useAction } from '../features/interview/useAction'

const label = { pending: '待开始', in_progress: '进行中', completed: '已完成', terminated: '提前终止', interrupted: '异常中断' }
const button = 'app-button app-button-primary'
const outline = 'app-button app-button-outline'

function Notice({ error }: { error: unknown }) { return error ? <div className="alert error" role="alert">{typeof error === 'string' ? error : errorText(error)}</div> : null }
function Head({ title, children }: { title: string; children: React.ReactNode }) { return <div className="page-head"><div className="eyebrow">MOCK INTERVIEW</div><h1>{title}</h1><p>{children}</p></div> }

export function InterviewConfigPage() {
  const navigate = useNavigate()
  const presets = useQuery({ queryKey: ['interview-presets'], queryFn: interviewApi.presets })
  const [kind, setKind] = useState<'bank' | 'role'>('bank')
  const [presetId, setPresetId] = useState('')
  const [mode, setMode] = useState<'practice' | 'formal'>('practice')
  const [limit, setLimit] = useState<'count' | 'time'>('count')
  const [count, setCount] = useState(3)
  const [minutes, setMinutes] = useState(30)
  const [jd, setJd] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const action = useAction('create')
  const questions = useQuery({ queryKey: ['interview-preset-questions', presetId], queryFn: () => interviewApi.questions(presetId), enabled: !!presetId })
  const choices = presets.data?.filter(p => p.kind === kind) ?? []
  const shortage = limit === 'count' && questions.data !== undefined && count > questions.data.length
  const jdTooLong = Array.from(jd).length > 5000
  const create = async () => {
    const body = { preset_id: presetId, mode, limit_type: limit, main_limit: limit === 'count' ? count : null, duration_seconds: limit === 'time' ? minutes * 60 : null, jd: kind === 'role' && jd ? jd : null, difficulty: difficulty || null }
    const result = await action.send<{ id: string }>('/interviews', body)
    if (result?.id) navigate(`/interviews/${result.id}`)
  }
  const recover = async () => { const result = await action.send<{ id: string }>(); if (result?.id) navigate(`/interviews/${result.id}`) }
  return <><Head title="配置一场模拟面试">选择面试方向、练习方式与限制，开始前可先了解规则。</Head>
    <div className="interview-config-grid"><div className="interview-stack">
      <section className="surface-card interview-section"><div className="section-kicker">01 / 面试方向</div><h2>选择题库或岗位</h2><div className="interview-choice-row">
        {([['bank','标准题库','围绕技术知识进行练习'],['role','预设岗位','结合岗位方向进行面试']] as const).map(([value,title,desc]) => <button key={value} className={`interview-choice ${kind === value ? 'selected' : ''}`} onClick={() => { setKind(value); setPresetId('') }}><strong>{title}</strong><small>{desc}</small></button>)}
      </div>
      {presets.isPending && <p className="interview-hint">正在加载预设...</p>}<Notice error={presets.error}/>
      {!presets.isPending && !presets.isError && !choices.length && <div className="alert info">当前没有可用的{kind === 'bank' ? '标准题库' : '岗位预设'}，正式内容审核后才能开始面试。<Link className="minor-link" to="/settings">查看使用指引</Link></div>}
      {choices.length > 0 && <label className="interview-field">选择预设<select value={presetId} onChange={e => setPresetId(e.target.value)}><option value="">请选择</option>{choices.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
      {presetId && <p className="interview-hint">{questions.isPending ? '正在检查题量...' : questions.isError ? '题库信息加载失败。' : `可用主问题：${questions.data?.length ?? 0} 道`}</p>}
      {kind === 'role' && <label className="interview-field">岗位 JD（可选）<textarea value={jd} onChange={e => setJd(e.target.value)} placeholder="粘贴岗位描述，最多 5000 个字符"/><small>{Array.from(jd).length} / 5000 字符；根据可识别的技术关键词优先匹配题目，不足时使用同题库其他题目。</small></label>}
      <label className="interview-field">题目难度<select value={difficulty} onChange={e => setDifficulty(e.target.value)}><option value="">不限难度</option><option value="basic">基础</option><option value="intermediate">进阶</option><option value="challenge">挑战</option></select><small>旧版题库可能没有难度标记；题量不足时可切换为不限难度。</small></label>
      </section>
      <section className="surface-card interview-section"><div className="section-kicker">02 / 面试方式</div><h2>选择模式</h2><div className="interview-choice-row">{([['practice','练习模式','可跳题，作答后可查看反馈'],['formal','正式模式','结束前不展示反馈和评分']] as const).map(([value,title,desc]) => <button key={value} className={`interview-choice ${mode === value ? 'selected' : ''}`} onClick={() => setMode(value)}><strong>{title}</strong><small>{desc}</small></button>)}</div></section>
      <section className="surface-card interview-section"><div className="section-kicker">03 / 面试限制</div><h2>设置面试节奏</h2><div className="filter-buttons"><button className={`filter ${limit === 'count' ? 'selected' : ''}`} onClick={() => setLimit('count')}>按题数</button><button className={`filter ${limit === 'time' ? 'selected' : ''}`} onClick={() => setLimit('time')}>按时长</button></div>
      {limit === 'count' ? <label className="interview-field">主问题数量<input type="number" min="3" step="1" value={count} onChange={e => setCount(Number(e.target.value))}/><small>至少 3 道主问题；每题最多 2 次追问，不占主问题数量。30 分钟无有效活动将中断。</small></label> : <label className="interview-field">面试时长（分钟）<input type="number" min="1" step="1" value={minutes} onChange={e => setMinutes(Number(e.target.value))}/><small>时长结束由服务端结算；题库耗尽后的处理规则尚待确认。</small></label>}
      {shortage && <div className="alert error">当前题库题量不足，请减少题数或选择其他题库。</div>}{jdTooLong && <div className="alert error">岗位 JD 超过 5000 个 Unicode 字符。</div>}
      </section></div>
      <aside className="surface-card interview-summary"><span className="interview-icon"><Mic size={23}/></span><h2>准备开始</h2><p>正常完成需要至少两道不同主问题有有效回答。提前结束后仅可查看文字复盘，不能继续作答。</p><Notice error={action.error}/>
      {action.pending ? <><p className="interview-hint">上一次创建请求尚未确认，请恢复原请求以避免重复创建。</p><button className={button} disabled={action.busy} onClick={() => void recover()}>恢复创建请求</button></> : <button className={button} disabled={!presetId || questions.isPending || questions.isError || !questions.data?.length || shortage || jdTooLong || (limit === 'count' ? !Number.isInteger(count) || count < 3 : !Number.isInteger(minutes) || minutes < 1) || action.busy} onClick={() => void create()}>创建面试 <ArrowRight size={16}/></button>}
      <Link className="minor-link" to="/interviews">查看面试记录</Link></aside>
    </div></>
}

export function InterviewHistoryPage() {
  const completed = useQuery({ queryKey: ['interviews','history','completed'], queryFn: () => interviewApi.history('completed') })
  const incomplete = useQuery({ queryKey: ['interviews','history','incomplete'], queryFn: () => interviewApi.history('incomplete') })
  const active = useQuery({ queryKey: ['interviews','history','active'], queryFn: () => interviewApi.history('in_progress') })
  const pending = useQuery({ queryKey: ['interviews','history','pending'], queryFn: () => interviewApi.history('pending') })
  const sections = [['进行中与待开始', [...(active.data ?? []), ...(pending.data ?? [])]], ['已完成', completed.data ?? []], ['未完成', incomplete.data ?? []]] as const
  return <><div className="row-between"><Head title="面试记录">查看已完成的报告，或回顾提前结束的有效作答。</Head><Link className={button} to="/interviews/new">开始新面试</Link></div>
    {[completed,incomplete,active,pending].some(q => q.isError) && <div className="alert error">面试记录加载失败，请刷新页面重试。</div>}
    {sections.map(([title, items]) => <section key={title}><div className="section-title"><h2>{title}</h2><span className="quiet-text">{items.length} 场</span></div>{items.length ? <div className="interview-list">{items.map(item => <Link key={item.id} to={item.status === 'pending' || item.status === 'in_progress' ? `/interviews/${item.id}` : `/interviews/${item.id}/report`} className="surface-card interview-history"><span className="interview-icon"><FileText size={19}/></span><div><strong>{item.preset?.name || '模拟面试'}</strong><small>{item.mode === 'practice' ? '练习模式' : '正式模式'} · {new Date(item.created_at).toLocaleString('zh-CN')}</small></div><span className="pill teal">{label[item.status]}</span><ArrowRight size={16}/></Link>)}</div> : <div className="surface-card empty-state">暂无{title}记录</div>}</section>)}
  </>
}

function AIAction({ id, kind, target, disabled, onComplete }: { id: string; kind: 'followup' | 'feedback' | 'report'; target: string; disabled?: boolean; onComplete?: () => void }) {
  const action = useAction(`${id}:ai:${kind}:${target}`, id)
  const result = action.result
  const body = kind === 'report' ? { type: target } : { answer_id: target }
  const path = `/interviews/${id}/ai/${kind}`
  const handled = useRef<string | null>(null)
  useEffect(() => {
    if (result?.status === 'complete' && result.id && handled.current !== result.id) {
      handled.current = result.id
      onComplete?.()
    }
  }, [result?.status, result?.id, onComplete])
  const run = async () => { const response = await action.send<Operation>(path, body, true); if (response?.status === 'no_content') onComplete?.() }
  const running = action.busy || result?.status === 'running'
  const caption = kind === 'followup' ? '生成追问' : kind === 'feedback' ? '获取本题反馈' : '生成复盘报告'
  return <div className="interview-ai">
    {!result || result.status === 'failed' ? <button className={outline} disabled={disabled || action.busy || (result?.status === 'failed' && result.retryable === false)} onClick={() => void run()}><Sparkles size={15}/>{action.pending ? '恢复或重试' : caption}</button> : null}
    {running && <span className="interview-hint">模型处理中，可刷新页面后恢复操作状态。关闭标签页可能丢失恢复信息，请先通过面试记录确认结果，避免重复提交。</span>}
    {action.pending && !result && !action.busy && <p className="interview-hint">请求结果尚未确认，恢复时会复用原请求；服务端可能仍在处理。</p>}
    {action.operationError && <button className="minor-link" onClick={() => void action.refreshOperation()}>操作状态查询失败，重新查询</button>}
    {result?.status === 'failed' && <p className="interview-hint">{result.error || '模型操作失败。'}{result.retryable === false ? ' 已达到重试上限。' : ''}</p>}
    {result?.status === 'complete' && result.result?.feedback && <div className="interview-feedback"><strong>练习反馈</strong><p>{result.result.feedback}</p></div>}
    {result?.status === 'complete' && kind === 'followup' && <button className="minor-link" onClick={() => onComplete?.()}>追问已生成，刷新题目</button>}
    {result?.status === 'complete' && kind === 'report' && <button className="minor-link" onClick={() => onComplete?.()}>报告已生成，查看报告</button>}
    {result?.status === 'no_content' && <p className="interview-hint">没有有效作答，暂无可复盘内容。</p>}
    <Notice error={action.error}/>
  </div>
}

function CurrentQuestion({ data, current, main, refresh, action }: { data: Interview; current: Question; main: Question; refresh: () => void; action: ReturnType<typeof useAction> }) {
  const [answer, setAnswer] = useState('')
  const base = `/interviews/${data.id}`
  const submit = async (skip = false) => { const done = await action.send(`${base}/answers`, { question_id: current.id, content: skip ? '' : answer, skip }); if (done) { setAnswer(''); refresh() } }
  const close = async () => { if (await action.send(`${base}/questions/close`, { question_id: main.id })) refresh() }
  const recover = async () => { if (await action.send()) refresh() }
  const followups = data.questions.filter(q => q.main_number === data.main_count && q.depth > 0).length
  return <><div className="surface-card interview-question"><div className="row-between"><span className="pill teal">{current.depth ? `追问 ${followups} / 2` : `主问题 ${current.main_number}${data.main_limit ? ` / ${data.main_limit}` : ''}`}</span><span className="quiet-text">{data.mode === 'practice' ? '练习模式' : '正式模式'}</span></div><h2>{current.content}</h2>
    {current.answer ? <div className="interview-answer-saved"><strong>{current.answer.kind === 'skip' ? '已跳过' : '已提交的回答'}</strong><p>{current.answer.content || '本题未作答'}</p></div> : <><label className="interview-field">你的回答<textarea value={answer} onChange={e => setAnswer(e.target.value)} maxLength={12000} placeholder="在这里输入你的思路和回答..."/></label><div className="interview-actions"><button className={button} disabled={action.busy || !!action.pending || !answer.trim()} onClick={() => void submit()}>提交回答</button>{data.mode === 'practice' && <button className={outline} disabled={action.busy || !!action.pending} onClick={() => void submit(true)}>跳过此题</button>}</div></>}
    {action.pending && <div className="alert info">上一次写入结果尚未确认。<button disabled={action.busy} onClick={() => void recover()}>恢复原请求</button></div>}<Notice error={action.error}/>
    {current.answer && !action.pending && <div className="interview-actions interview-next-actions">{current.answer.kind === 'answer' && data.mode === 'practice' && <AIAction key={`feedback-${current.answer.id}`} id={data.id} kind="feedback" target={current.answer.id} onComplete={refresh}/>} {current.answer.kind === 'answer' && followups < 2 && current.depth < 2 && <AIAction key={`follow-${current.answer.id}`} id={data.id} kind="followup" target={current.answer.id} onComplete={refresh}/>}<button className={button} disabled={action.busy} onClick={() => void close()}>结束本题 <ArrowRight size={15}/></button></div>}
    </div></>
}

export function InterviewSessionPage() {
  const { interviewId = '' } = useParams()
  return <InterviewSession key={interviewId} interviewId={interviewId}/>
}

function InterviewSession({ interviewId }: { interviewId: string }) {
  const detail = useQuery({ queryKey: ['interviews', 'detail', interviewId], queryFn: () => interviewApi.detail(interviewId), refetchInterval: 15000 })
  const action = useAction(`${interviewId}:write`, interviewId)
  const data = detail.data
  const currentSet = data?.questions.filter(q => q.main_number === data.main_count) ?? []
  const main = currentSet.find(q => q.depth === 0)
  const current = currentSet.at(-1)
  const refresh = () => { void detail.refetch() }
  const post = async (suffix: string) => { if (await action.send(`/interviews/${interviewId}/${suffix}`)) refresh() }
  const terminate = () => { if (window.confirm('确定提前结束？已提交回答会保留，结束后不能继续作答。')) void post('terminate') }
  if (detail.isPending) return <div className="surface-card empty-state">正在读取面试状态...</div>
  if (!data) return <><Head title="无法读取面试">请检查面试地址或网络连接。</Head><Notice error={detail.error}/><button className={outline} onClick={refresh}>重新加载</button></>
  const terminal = ['completed','terminated','interrupted'].includes(data.status)
  return <><div className="row-between"><Head title={data.preset?.name || '模拟面试'}>{label[data.status]} · {data.mode === 'practice' ? '练习模式' : '正式模式'} · 主问题 {data.main_count}{data.main_limit ? ` / ${data.main_limit}` : ''}</Head><Link className={outline} to="/interviews">面试记录</Link></div>{data.selection_notice && <div className="alert info">{data.selection_notice}</div>}
    {terminal ? <div className="surface-card interview-terminal"><FileText size={30}/><h2>{data.status === 'completed' ? '面试已完成' : '面试已结束'}</h2><p>{data.status === 'completed' ? '可以生成并查看完整报告。' : '此场次不能继续作答，只能查看有效回答的文字复盘。'}</p><Link className={button} to={`/interviews/${data.id}/report`}>查看复盘</Link></div> : <div className="interview-session-grid"><div className="interview-stack">
      {data.status === 'pending' && <div className="surface-card interview-section"><h2>准备好开始了吗？</h2><p>开始后由服务端记录时间；退出页面不会创建新的场次。</p><button className={button} disabled={action.busy || !!action.pending} onClick={() => void post('start')}>开始面试</button></div>}
      {data.status === 'in_progress' && (!main || main.closed_at) && <div className="surface-card interview-section"><span className="pill teal">{main ? '本题已结束' : '面试已开始'}</span><h2>{main ? '准备下一道主问题' : '准备第一道主问题'}</h2><p>题目从创建时确定的题库中获取。</p><button className={button} disabled={action.busy || !!action.pending} onClick={() => void post('questions/next')}>获取下一题 <ArrowRight size={15}/></button><p className="interview-hint">若时长模式题库已耗尽，可等待时限到期或主动结束；耗尽策略尚待确认。</p></div>}
      {data.status === 'in_progress' && main && !main.closed_at && current && <CurrentQuestion key={current.id} data={data} main={main} current={current} refresh={refresh} action={action}/>}
      {(!current || main?.closed_at) && action.pending && <div className="alert info">写入结果尚未确认。<button disabled={action.busy} onClick={() => void action.send().then(refresh)}>恢复原请求</button></div>}
      {(!current || main?.closed_at) && <Notice error={action.error}/>}
    </div><aside className="surface-card interview-summary"><span className="interview-icon"><Clock3 size={22}/></span><h2>面试进度</h2><p>已出现 {data.main_count} 道主问题<br/>有效主问题回答 {data.valid_main_count} 道</p>{data.deadline_at ? <p>服务端截止时间<br/><strong>{new Date(data.deadline_at).toLocaleString('zh-CN')}</strong></p> : <p>题数模式在 30 分钟无有效活动后中断；查询和刷新不会延长期限。</p>}<p>面试状态以服务端为准，页面会定期刷新。关闭标签页可能丢失未确认请求，请从面试记录核对已保存内容，勿重复提交。</p>{data.status === 'in_progress' && <button className={outline} disabled={action.busy || !!action.pending} onClick={terminate}>提前结束</button>}</aside></div>}
  </>
}

function TaskChoice({ interviewId, answerId, review }: { interviewId: string; answerId: string; review: string }) {
  const topics = useTopics()
  const [topicId, setTopicId] = useState('')
  const client = useQueryClient()
  const create = useMutation({ mutationFn: () => api.createTask({ interview_id: interviewId, answer_id: answerId, topic_id: topicId }), onSuccess: () => client.invalidateQueries({ queryKey: ['tasks'] }) })
  const tokens = (text: string) => { const normalized = text.toLowerCase(); return [...(normalized.match(/[a-z0-9_]{2,}/g) ?? []), ...Array.from(normalized).slice(0, -1).map((c, i) => c + normalized[i + 1]).filter(s => /^[\u4e00-\u9fff]{2}$/.test(s))] }
  const reviewTerms = new Set(tokens(review))
  const ranked = [...(topics.data ?? [])].map(topic => ({ topic, score: tokens(`${topic.title} ${topic.summary}`).filter(term => reviewTerms.has(term)).length })).sort((a, b) => b.score - a.score)
  return <div><p className="interview-hint">根据复盘内容匹配相关专题（仅供参考），由你确认是否加入学习计划。</p>
    <select aria-label="选择学习专题" value={topicId} onChange={e => setTopicId(e.target.value)}><option value="">选择专题</option>{ranked.map(({ topic, score }) => <option key={topic.id} value={topic.id}>{score > 0 ? '建议：' : ''}{topic.title}</option>)}</select>{' '}
    <button className="app-button app-button-outline app-button-sm" disabled={!topicId || create.isPending} onClick={() => create.mutate()}>确认加入学习计划</button>
    {create.isSuccess && <p>已加入学习计划。<Link className="minor-link" to="/tasks">查看任务</Link></p>}<Notice error={create.error}/></div>
}

function ReportBody({ interviewId, report, full, questions }: { interviewId: string; report: Report; full: boolean; questions: Question[] }) {
  const byAnswer = new Map(questions.filter(q => q.answer).map(q => [q.answer!.id, q]))
  return <div className="interview-stack"><div className="surface-card interview-section"><div className="section-kicker">INTERVIEW REVIEW</div><h2>{full ? '完整面试报告' : '部分文字复盘'}</h2><p>{report.summary}</p>{full && !report.summary.startsWith('【模拟复盘】') && typeof report.overall_score === 'number' && <div className="interview-score"><strong>{report.overall_score}</strong><span> / 100<br/>候选量表，尚待产品确认</span></div>}</div>
    {report.items.map(item => { const q = byAnswer.get(item.answer_id); return <div className="surface-card interview-section" key={item.answer_id}><span className="pill teal">{q?.depth ? '追问' : '主问题'} {q?.main_number ?? ''}</span><h3>{q?.content ?? '已提交问题'}</h3><p className="interview-hint">你的回答：{q?.answer?.content ?? '未找到对应回答'}</p><p>{item.review}</p><TaskChoice interviewId={interviewId} answerId={item.answer_id} review={item.review}/></div> })}</div>
}

export function InterviewReportPage() {
  const { interviewId = '' } = useParams()
  return <InterviewReport key={interviewId} interviewId={interviewId}/>
}

function InterviewReport({ interviewId }: { interviewId: string }) {
  const detail = useQuery({ queryKey: ['interviews', 'detail', interviewId], queryFn: () => interviewApi.detail(interviewId) })
  const terminal = !!detail.data && ['completed','terminated','interrupted'].includes(detail.data.status)
  const report = useQuery({ queryKey: ['interviews','report',interviewId], queryFn: () => interviewApi.report(interviewId), enabled: terminal })
  if (detail.isPending) return <div className="surface-card empty-state">正在读取面试...</div>
  if (!detail.data) return <><Notice error={detail.error}/><Link className="minor-link" to="/interviews">返回面试记录</Link></>
  if (!terminal) return <><Head title="报告尚未开放">面试尚未结束，正式模式进行中不会展示评价或评分。</Head><Link className={outline} to={`/interviews/${interviewId}`}>返回面试</Link></>
  const full = detail.data.status === 'completed'
  return <><div className="row-between"><Head title={full ? '面试报告' : '面试复盘'}>{label[detail.data.status]} · {full ? '完整报告' : '仅展示有效作答的文字复盘'}</Head><Link className={outline} to="/interviews">返回记录</Link></div><Notice error={report.error}/>{report.isPending && <div className="surface-card empty-state">正在读取报告...</div>}
    {report.data?.status === 'no_content' && <div className="surface-card empty-state">本场没有有效作答，暂无可复盘内容。</div>}
    {report.data?.status === 'not_requested' && <div className="surface-card interview-terminal"><Sparkles size={28}/><h2>报告尚未生成</h2><p>{full ? '基于已提交的回答生成完整报告。' : '只对实际有效回答生成文字复盘，不包含评分。'}</p><AIAction id={interviewId} kind="report" target={full ? 'full' : 'partial'} onComplete={() => void report.refetch()}/></div>}
    {report.data?.status === 'ready' && report.data.result && <ReportBody interviewId={interviewId} report={report.data.result} full={full} questions={detail.data.questions}/>}
  </>
}
