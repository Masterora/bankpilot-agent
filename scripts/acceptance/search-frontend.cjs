/**
 * 文件职责：验证搜索前端请求隔离与地址恢复。
 * 主要内容：检查迟到查询、退出、分页双版本、显式重试及 URL 条件编码。
 * 关键边界：只执行确定性状态回归；真实浏览器布局与交互需单独验收。
 */
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path'), assert = require('node:assert/strict')
const ts = require('../../web/node_modules/typescript')
const compile = file => ts.transpileModule(fs.readFileSync(path.join(__dirname, '../../web/src', file), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function harness(api) {
 let cursor=0;const slots=[],effects=[],cleanup=[],listeners=new Map()
 const react={
  useState(value){const i=cursor++;if(!(i in slots))slots[i]=value;return [slots[i],v=>slots[i]=typeof v==='function'?v(slots[i]):v]},
  useRef(value){const i=cursor++;return slots[i]??=( {current:value} )},
  useCallback(fn,deps){const i=cursor++;if(!slots[i]||deps.some((v,n)=>v!==slots[i].deps[n]))slots[i]={fn,deps};return slots[i].fn},
  useEffect(fn,deps){const i=cursor++;if(!slots[i]||deps.some((v,n)=>v!==slots[i][n])){slots[i]=deps;effects.push(()=>{cleanup[i]?.();cleanup[i]=fn()})}},
 }
 const module={exports:{}}
 vm.runInNewContext(compile('features/ledger/useTransactionSearch.ts'),{module,exports:module.exports,require:key=>key==='react'?react:key==='../../api'?{api}:{versions:p=>({expected_revision:p.ledger_revision,expected_search_version:p.search_version})},window:{addEventListener:(k,v)=>listeners.set(k,v),removeEventListener:k=>listeners.delete(k)}})
 return {render(active=true){cursor=0;const state=module.exports.useTransactionSearch(active);effects.splice(0).forEach(fn=>fn());return state},event:k=>listeners.get(k)?.(),dispose:()=>cleanup.forEach(fn=>fn?.())}
}
async function main(){
 const first=deferred(),second=deferred();let n=0
 const h=harness({search:()=>++n===1?first.promise:second.promise});let state=h.render()
 const a=state.query({text:'a'}),b=state.query({text:'b'})
 second.resolve({filters:{text:'b'},items:[{id:'b'}]});await b
 first.resolve({filters:{text:'a'},items:[{id:'a'}]});await a
 state=h.render();assert.equal(state.page.items[0].id,'b');h.dispose()
 console.log('PASS late search response cannot replace the newer executed filters')
 const pending=deferred();const stopped=harness({search:()=>pending.promise});state=stopped.render()
 const op=state.query({text:'private'});stopped.event('bankpilot-logout');pending.resolve({items:[{id:'old'}]});await op
 state=stopped.render();assert.equal(state.page,null);assert.equal(state.busy,false);stopped.dispose()
 console.log('PASS logout fences pending search results')
 let calls=[];const pages=harness({search:async(...args)=>{calls.push(args);if(calls.length===2)throw Error('stale');return {items:[{id:'one'}],filters:{text:'x'},ledger_revision:7,search_version:'search-v1'}}})
 state=pages.render();await state.query({text:'x'});state=pages.render();await state.query(state.page.filters,20,state.page)
 state=pages.render();assert.equal(calls[1][2].expected_revision,7);assert.equal(state.stale,true);assert.equal(state.page.items[0].id,'one')
 await state.query(state.page.filters);state=pages.render();assert.equal(calls[2][1],0);assert.equal(calls[2][2],undefined);assert.equal(state.stale,false);pages.dispose()
 console.log('PASS pagination carries both versions; conflict preserves labelled old result; explicit retry starts new first page')
 const module={exports:{}};let hash='#page=review&start=2026-09-01&end=2026-09-30'
 const window={location:{get hash(){return hash}},history:{pushState:(_a,_b,v)=>{hash=v}}}
 vm.runInNewContext(compile('features/ledger/search.ts'),{module,exports:module.exports,require:()=>({}),window,URLSearchParams})
 module.exports.writeSearch({start_date:'2026-09-01',end_date:'2026-09-30',text:'merchant & 100%'})
 assert.equal(module.exports.readSearch({start:'2026-09-01',end:'2026-09-30'}).text,'merchant & 100%')
 assert.equal(new URLSearchParams(hash.slice(1)).get('page'),'review')
 console.log('PASS explicit filter URL encoding round-trips literal personal text without query-string logging')
}
main().catch(e=>{console.error(e);process.exitCode=1})
