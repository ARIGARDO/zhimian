const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { webcrypto } = require('node:crypto')

function compile(file, requires, globals = {}) {
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  const mod = { exports: {} }
  vm.runInNewContext(js, { module: mod, exports: mod.exports, require: name => requires[name] ?? require(name), ...globals })
  return mod.exports
}
class ApiError extends Error { constructor(status, message) { super(message); this.status = status } }
function harness(fetch) {
  const storage = new Map(), states = []; let cursor = 0
  const sessionStorage = { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) }
  const api = compile('src/features/interview/api.ts', { '../../api/client': { ApiError } }, { sessionStorage, crypto: webcrypto, AbortController, fetch, window: { setTimeout, clearTimeout } })
  const fakeReact = {
    useState(initial) { const i = cursor++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = value }] },
    useRef(initial) { const i = cursor++; if (!(i in states)) states[i] = { current: initial }; return states[i] },
  }
  const hook = compile('src/features/interview/useAction.ts', { react: fakeReact, '@tanstack/react-query': { useQueryClient: () => ({ invalidateQueries: async () => {} }), useQuery: () => ({ data: undefined, isError: false, refetch() {} }) }, '../../api/client': { ApiError }, './api': api }, { DOMException })
  return { api, storage, render(slot, id) { cursor = 0; return hook.useAction(slot, id) } }
}
const response = body => ({ ok: true, json: async () => body })

test('连续点击仅发送一次，数据库已写入但响应丢失时按原键和原体恢复', async () => {
  const requests = []; let finish
  const h = harness((url, init) => { requests.push([url, init.headers['Idempotency-Key'], init.body]); if (requests.length === 1) return new Promise((_, reject) => { finish = () => reject(new Error('连接断开')) }); return Promise.resolve(response({ id: 'saved' })) })
  let action = h.render('A:write', 'A')
  const first = action.send('/interviews/A/answers', { question_id: 'q', content: '回答', skip: false })
  assert.equal(await action.send('/interviews/A/answers', { question_id: 'q', content: '回答', skip: false }), null)
  assert.equal(requests.length, 1)
  finish(); await first
  action = h.render('A:write', 'A'); assert.ok(action.pending)
  assert.equal((await action.send()).id, 'saved')
  assert.deepEqual(requests[0], requests[1])
  assert.equal(h.api.loadPending('A:write'), null)
})

test('代理 504 保留原请求并在刷新后按原键重试', async () => {
  let attempts = 0; const requests = []
  const h = harness(async (url, init) => { requests.push([url, init.headers['Idempotency-Key'], init.body]); attempts++; return attempts === 1 ? { ok: false, status: 504, json: async () => ({}) } : response({ id:'ok' }) })
  let action = h.render('A:write', 'A')
  assert.equal(await action.send('/interviews/A/answers', { question_id:'q', content:'答', skip:false }), null)
  const saved = h.api.loadPending('A:write'); assert.ok(saved)
  // 新标签实例模拟同一标签页刷新后的存储读取。
  assert.equal((await h.api.interviewApi.post(saved)).id, 'ok')
  assert.deepEqual(requests[0], requests[1])
})

test('模型失败重试仍复用原键并能读取服务端的尝试上限', async () => {
  let n = 0; const keys = []
  const h = harness(async (url, init) => { keys.push(init.headers['Idempotency-Key']); n++; return response({ id:'op', status:'failed', retryable:n < 3 }) })
  let action = h.render('A:ai:feedback:q', 'A')
  for (let i=0;i<3;i++) { const result = await action.send('/interviews/A/ai/feedback', {answer_id:'q'}, true); assert.equal(result.retryable, i < 2); action = h.render('A:ai:feedback:q', 'A') }
  assert.equal(new Set(keys).size, 1)
})

function pages(data, report, actionResult = null) {
  let id = 'A'
  const params = { useParams: () => ({ interviewId:id }), useNavigate: () => () => {}, Link: ({children}) => React.createElement('a', null, children) }
  const icons = new Proxy({}, { get: () => () => null })
  const useQuery = ({queryKey}) => ({ data: queryKey[1] === 'detail' ? data : report, isPending:false, isError:false, refetch() {} })
  const page = compile('src/pages/InterviewPage.tsx', { react: React, 'react/jsx-runtime': require('react/jsx-runtime'), 'react-router-dom':params, '@tanstack/react-query': { useQuery }, 'lucide-react':icons, '../features/interview/api':{}, '../features/interview/useAction':{ errorText:String, useAction:() => ({pending:null,busy:false,error:'',result:actionResult,send(){}}) } })
  return { ...page, setId(value) { id=value } }
}
const question = { id:'q', main_number:1, depth:0, position:0, content:'问题', closed_at:null, answer:null }
const interview = { id:'A', status:'in_progress', mode:'formal', preset:{name:'测试'}, main_count:1, main_limit:3, limit_type:'count', valid_main_count:0, questions:[question] }

test('切换面试时页面子树按场次重建，待恢复请求不会沿用旧组件', () => {
  const p = pages(interview, null)
  const first = p.InterviewSessionPage(); p.setId('B'); const second = p.InterviewSessionPage()
  assert.equal(first.key, 'A'); assert.equal(second.key, 'B')
  assert.equal(second.props.interviewId, 'B')
  const reportB = p.InterviewReportPage(); assert.equal(reportB.key, 'B')
})

test('终态不能提交；正式模式进行中不提供跳题或评价', () => {
  let p = pages(interview, null)
  const active = renderToStaticMarkup(React.createElement(p.InterviewSessionPage))
  assert.match(active, /提交回答/); assert.doesNotMatch(active, /跳过此题|获取本题反馈|练习反馈/)
  p = pages({...interview, status:'terminated'}, null)
  const terminal = renderToStaticMarkup(React.createElement(p.InterviewSessionPage))
  assert.doesNotMatch(terminal, /提交回答|跳过此题|生成追问/)
})

test('未完成复盘不展示综合数字评分', () => {
  const p = pages({...interview, status:'terminated'}, {status:'ready',type:'partial',result:{summary:'文字复盘',overall_score:87,items:[]}})
  const html = renderToStaticMarkup(React.createElement(p.InterviewReportPage))
  assert.match(html, /部分文字复盘/); assert.doesNotMatch(html, /87|100|候选量表/)
})

test('模型操作达到尝试上限时禁用重试按钮', () => {
  const answered = {...question, answer:{id:'a',kind:'answer',content:'回答'}}
  const p = pages({...interview, mode:'practice', questions:[answered]}, null, {status:'failed',retryable:false,error:'已达到上限'})
  const html = renderToStaticMarkup(React.createElement(p.InterviewSessionPage))
  assert.match(html, /disabled=""[^>]*>恢复或重试|disabled=""[^>]*>获取本题反馈/)
  assert.match(html, /已达到重试上限/)
})
