const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const { webcrypto } = require('node:crypto')

function setup(fetch) {
  const source = fs.readFileSync('src/features/interview/api.ts', 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const saved = new Map()
  class ApiError extends Error { constructor(status, message) { super(message); this.status = status } }
  const module = { exports: {} }
  const context = { module, exports: module.exports, require: () => ({ ApiError }), crypto: webcrypto, AbortController, fetch,
    window: { setTimeout, clearTimeout }, sessionStorage: { setItem: (k,v) => saved.set(k,v), getItem: k => saved.get(k) ?? null, removeItem: k => saved.delete(k) } }
  vm.runInNewContext(js, context)
  return module.exports
}

test('断线后保存并重放同一幂等键与请求体', async () => {
  const requests = []
  const api = setup(async (url, init) => { requests.push({ url, key: init.headers['Idempotency-Key'], body: init.body }); return { ok: true, json: async () => ({ id: 'same' }) } })
  const pending = api.newPending('/interviews/i/answers', { question_id: 'q', content: '有效回答', skip: false })
  api.savePending('i:write', pending)
  await api.interviewApi.post(api.loadPending('i:write'))
  await api.interviewApi.post(api.loadPending('i:write'))
  assert.deepEqual(requests[0], requests[1])
  assert.match(requests[0].key, /^[a-f0-9]{32}$/)
  assert.equal(JSON.parse(requests[0].body).content, '有效回答')
  api.savePending('i:write', null)
  assert.equal(api.loadPending('i:write'), null)
})

test('服务端状态错误和到期响应可向页面反馈', async () => {
  const api = setup(async () => ({ ok: false, status: 409, json: async () => ({ end_reason: 'time_limit' }) }))
  await assert.rejects(api.interviewApi.post(api.newPending('/interviews/i/start')), e => e.status === 409 && e.message.includes('到期'))
})
