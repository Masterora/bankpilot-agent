/**
 * 文件职责：验证前端证据状态与请求竞争。
 * 主要内容：模拟请求顺序，检查证据合并、账本变化失效、迟到响应及失败重试。
 * 关键边界：属于状态回归，不证明真实浏览器的 DOM、布局或焦点行为。
 */
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '../../web')
const ts = require(path.join(root, 'node_modules/typescript'))
const tick = () => new Promise(resolve => setImmediate(resolve))
function load(file, mocks = {}, globals = {}) {
  const module = { exports: {} }
  const source = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  vm.runInNewContext(source, { module, exports: module.exports, require: key => mocks[key] ?? {}, ...globals })
  return module.exports
}
function harness(file, mocks) {
  let cursor = 0
  const slots = [], pending = [], cleanups = []
  const react = {
    useState(value) {
      const i = cursor++
      if (!(i in slots)) slots[i] = value
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value }]
    },
    useEffect(fn, deps) {
      const i = cursor++
      if (!slots[i] || deps.some((v, n) => v !== slots[i][n])) {
        slots[i] = deps
        pending.push(() => { cleanups[i]?.(); cleanups[i] = fn() })
      }
    },
  }
  const jsx = (type, props) => ({ type, props })
  const exports = load(file, { ...mocks, react, 'react/jsx-runtime': { jsx, jsxs: jsx } })
  return {
    render(props) { cursor = 0; const tree = exports.SpendingDetails(props); pending.splice(0).forEach(fn => fn()); return tree },
    dispose() { cleanups.forEach(fn => fn?.()) },
  }
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return null
  if (predicate(tree)) return tree
  const children = tree.props?.children
  for (const child of Array.isArray(children) ? children.flat(Infinity) : [children]) {
    const result = find(child, predicate)
    if (result) return result
  }
  return null
}
const button = (tree, label) => find(tree, n => n.type === 'button' && n.props.children === label)
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

async function main() {
  const { spendingRefs } = load('src/features/assistant/types.ts')
  const reference = { scope: { month: '2026-09-01', category: 'dining', currency: 'CNY' }, ledger_revision: 1, calculation_version: 'spending-v1' }
  assert.equal(spendingRefs([{ tool: 'spending', data: reference }, { tool: 'budgets', data: { spending_refs: [reference] } }]).length, 1)
  assert.equal(spendingRefs([{ tool: 'spending', data: reference }, { tool: 'spending', data: { ...reference, ledger_revision: 2 } }]).length, 2)
  console.log('PASS duplicate tool references merge only within the same scope and evidence versions')
  let events = [], ok = true
  const { api, ApiError } = load('src/api.ts', {}, {
    URLSearchParams, Event, window: { dispatchEvent: event => events.push(event.type) },
    fetch: async () => ({ ok, status: ok ? 204 : 409, json: async () => ({ detail: { code: 'conflict', message: 'conflict' } }) }),
  })
  await api.correctLedgerCategory('one', 'housing')
  await api.correctCategory('run', 'one', 'housing')
  await api.renameAccount('account', 'new name')
  await api.revokeImport('batch')
  await api.saveRelation({})
  assert.equal(events.length, 5)
  await api.saveBudget({})
  assert.equal(events.length, 5)
  ok = false
  await assert.rejects(api.correctLedgerCategory('one', 'housing'))
  assert.equal(events.length, 5)
  console.log('PASS ledger and Agent corrections invalidate evidence; budget writes and failures do not')

  const requests = []
  const page = harness('src/features/assistant/SpendingDetails.tsx', {
    '../../api': { ApiError, api: { spendingEvidence: () => { const d = deferred(); requests.push(d); return d.promise } } },
    '../../format': { formatMoney: v => v },
    '../../shared/apiErrors': { apiErrorMessage: () => 'read failed' },
    '../../shared/ui': { LoadingIndicator: 'loading' },
  })
  const summary = { scope: { month: '2026-09-01', category: 'dining', currency: 'CNY' }, calculated_at: 'now' }
  const props = { summary, copy: {}, locale: 'zh-CN', active: true, stale: false, onBack() {}, onRequery() {}, onInspect() {} }
  const response = (n, merchant) => ({ page: n, page_size: 20, total: 21, items: [{ transaction_id: merchant, merchant, contribution: '1.00', currency: 'CNY', booking_date: '2026-09-01', account_name: 'synthetic' }] })
  page.render(props)
  page.render({ ...props, active: false })
  requests[0].resolve(response(1, 'late-hidden'))
  await tick()
  page.render(props)
  assert.equal(requests.length, 2)
  requests[1].resolve(response(1, 'fresh'))
  await tick()
  let tree = page.render(props)
  assert(!JSON.stringify(tree).includes('late-hidden'))
  assert(JSON.stringify(tree).includes('fresh'))
  button(tree, '下一页').props.onClick()
  tree = page.render(props)
  assert(!JSON.stringify(tree).includes('fresh'))
  page.render({ ...props, stale: true })
  requests[2].resolve(response(2, 'late-stale'))
  await tick()
  tree = page.render({ ...props, stale: true })
  assert(button(tree, '重新查询'))
  assert(!JSON.stringify(tree).includes('late-stale'))
  console.log('PASS hidden/reopened evidence revalidates; page switch hides previous rows; stale response ignored')
  page.dispose()

  const retryRequests = []
  const retry = harness('src/features/assistant/SpendingDetails.tsx', {
    '../../api': { ApiError, api: { spendingEvidence: () => { const d = deferred(); retryRequests.push(d); return d.promise } } },
    '../../format': { formatMoney: v => v },
    '../../shared/apiErrors': { apiErrorMessage: () => 'read failed' },
    '../../shared/ui': { LoadingIndicator: 'loading' },
  })
  retry.render(props)
  retryRequests[0].reject(new Error('network'))
  await tick()
  tree = retry.render(props)
  button(tree, '重试').props.onClick()
  retry.render(props)
  retryRequests[1].reject(new ApiError('stale', 409, 'assistant_evidence_stale'))
  await tick()
  tree = retry.render(props)
  assert(button(tree, '重新查询'))
  assert(!button(tree, '重试'))
  assert(!find(tree, n => n.type === 'ol'))
  retry.dispose()
  console.log('PASS read failure supports retry; server version conflict discards details and requires a new query')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
