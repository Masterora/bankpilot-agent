/** Recovery lifecycle checks with controlled HTTP ordering; browser layout tested separately. */
const fs = require('node:fs')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('../../web/node_modules/typescript')
const tick = () => new Promise(resolve => setImmediate(resolve))
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return {promise, resolve, reject} }
function harness(api, storage = new Map()) {
  const slots = [], pending = [], cleanup = []
  let cursor = 0
  const react = {
    useState(value) { const i = cursor++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value }] },
    useRef(value) { const i = cursor++; if (!(i in slots)) slots[i] = {current:value}; return slots[i] },
    useCallback(fn, deps) { const i = cursor++; if (!slots[i] || deps.some((v,n) => v !== slots[i].deps[n])) slots[i] = {fn, deps}; return slots[i].fn },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || deps.some((v,n) => v !== slots[i][n])) { slots[i] = deps; pending.push(() => { cleanup[i]?.(); cleanup[i] = fn() }) } },
  }
  class ApiError extends Error {}
  const module = {exports:{}}
  const code = ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname,'../../web/src/features/assistant/useConversations.ts'),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022}}).outputText
  const sessionStorage = { getItem:k=>storage.get(k) ?? null, setItem:(k,v)=>storage.set(k,v), removeItem:k=>storage.delete(k) }
  vm.runInNewContext(code, {module, exports:module.exports, require:key=>key==='react'?react:{api,ApiError}, sessionStorage, window:{setInterval:()=>1,addEventListener:()=>{},removeEventListener:()=>{}}, clearInterval:()=>{}, Map})
  return { render() { cursor=0; const result=module.exports.useConversations('user',false,'2026-09'); pending.splice(0).forEach(fn=>fn()); return result }, dispose() { cleanup.forEach(fn=>fn?.()) }, storage }
}
const detail = (id, text=id) => ({conversation:{id,month:'2026-09-01',scope:null},turns:[{id,question:text,status:'completed',sequence:1}],next_before:null,turn_limit:200})
const input = {protocol_version:2,creation_id:'create',request_id:'request',question:'original',month:'2026-09-01',locale:'zh-CN',spending_context:null}
const empty = async () => ({items:[],next_cursor:null,recent_id:null})
async function main() {
  const a=deferred(), b=deferred()
  const h=harness({assistantHistory:empty, assistantConversation:id=>id==='a'?a.promise:b.promise})
  let state=h.render(); await tick(); state=h.render()
  const first=state.load('a'), second=state.load('b')
  b.resolve(detail('b')); await second
  a.resolve(detail('a')); await first
  state=h.render(); assert.equal(state.id,'b'); assert.equal(state.turns[0].question,'b'); h.dispose()
  console.log('PASS late history response cannot overwrite another conversation')

  const store=new Map([['assistant:user',JSON.stringify(input)]])
  let modelCalls=0
  const restored=harness({assistantHistory:empty, assistantLookup:async()=>({conversation_id:'saved'}), assistantConversation:async()=>detail('saved'), assistantTurn:async()=>{modelCalls++}},store)
  restored.render(); await tick(); await tick(); state=restored.render()
  assert.equal(state.id,'saved'); assert.equal(state.unknown,null); assert.equal(store.has('assistant:user'),false); assert.equal(modelCalls,0); restored.dispose()
  console.log('PASS refresh looks up original identity without replay and removes accepted question body')

  let sent
  const response=deferred()
  const unknown=harness({assistantHistory:empty, assistantLookup:async()=>{throw Error('unknown')}, assistantTurn:payload=>{sent=payload; return response.promise},assistantConversation:async()=>detail('saved')})
  state=unknown.render(); await tick(); state=unknown.render()
  const sending=state.send(input)
  assert.equal(JSON.parse(unknown.storage.get('assistant:user')).question,'original')
  response.reject(Error('network'))
  await sending; state=unknown.render()
  assert.equal(state.unknown.request_id,input.request_id); assert.equal(sent,input)
  unknown.dispose()
  console.log('PASS network ambiguity preserves full original input and identity for explicit retry')

  const delayed=deferred()
  const stopped=harness({assistantHistory:empty,assistantTurn:()=>delayed.promise,assistantConversation:async()=>detail('late')})
  state=stopped.render(); await tick(); state=stopped.render()
  const operation=state.send(input); stopped.dispose(); stopped.storage.clear()
  delayed.resolve({conversation_id:'late'}); await operation
  assert.equal(stopped.storage.size,0)
  console.log('PASS response after logout/unmount cannot recreate recovery storage')
}
main().catch(error=>{console.error(error);process.exitCode=1})
