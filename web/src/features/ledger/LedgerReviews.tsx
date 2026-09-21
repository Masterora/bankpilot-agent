/**
 * 文件职责：展示并保存当前搜索结果的规则核查判断。
 * 主要内容：按当前页交易 ID、期间和账本版本读取核查投影，展示证据并提交用户结论。
 * 关键边界：不计算金额或异常；请求切换隔离迟到结果，保存依赖服务端重新验证证据。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ReviewItem } from '../../types'
import type { ReviewPeriod } from '../../shared/period'
import type { SearchItem, SearchPage } from './search'
import { searchError } from './search'

export interface ProjectedReview { review: ReviewItem; evidence: SearchItem[]; evidence_total: number; evidence_offset: number }
export interface ReviewProjection { items: ProjectedReview[]; offset: number; total_count: number; ledger_revision: number }
export interface ProjectionRequest { start_date: string; end_date: string; transaction_ids: string[]; expected_revision: number; offset?: number; evidence_key?: string; evidence_offset?: number }
export function LedgerReviews({ page, period, english: en }: { page: SearchPage; period: ReviewPeriod; english: boolean }) {
  const [result, setResult] = useState<ReviewProjection | null>(null)
  const [error, setError] = useState('')
  const [offset, setOffset] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const request: ProjectionRequest = { start_date: period.start, end_date: period.end, transaction_ids: page.items.map(item => item.id), expected_revision: page.ledger_revision, offset }
  const key = JSON.stringify(request)
  useEffect(() => {
    if (!page.items.length) return
    let alive = true
    setResult(null); setError('')
    api.reviewProjection(JSON.parse(key)).then(data => { if (alive) setResult(data) }).catch(cause => { if (alive) setError(searchError(cause, en)) })
    return () => { alive = false }
  }, [key, attempt, en, page.items.length])
  return <section><h2>{en ? 'Review exceptions' : '异常核查'}</h2>
    {error && <p role="alert">{error}<button onClick={() => setAttempt(v => v + 1)}>{en ? 'Retry' : '重试'}</button></p>}
    {!result && !error && <p role="status">{en ? 'Loading…' : '加载中…'}</p>}
    {result?.items.map(item => <ReviewForm key={item.review.key} initial={item} request={request} english={en} />)}
    {result?.total_count === 0 && <p>{en ? 'No review items for this page.' : '本页无核查项。'}</p>}
    {result && result.total_count > 20 && <nav><button disabled={!offset} onClick={() => setOffset(v => v - 20)}>{en ? 'Previous' : '上一页'}</button><button disabled={offset + 20 >= result.total_count} onClick={() => setOffset(v => v + 20)}>{en ? 'Next' : '下一页'}</button></nav>}
  </section>
}
function ReviewForm({ initial, request, english: en }: { initial: ProjectedReview; request: ProjectionRequest; english: boolean }) {
  const [item, setItem] = useState(initial)
  const [state, setState] = useState(initial.review.state)
  const [note, setNote] = useState(initial.review.note)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [stale, setStale] = useState(false)
  async function more(offset: number) {
    setBusy(true)
    try { const data = await api.reviewProjection({ ...request, evidence_key: item.review.key, evidence_offset: offset }); setItem(data.items[0]) }
    catch (cause) { setMessage(searchError(cause, en)); setStale(true) }
    finally { setBusy(false) }
  }
  return <form className="import-report" onSubmit={async event => {
    event.preventDefault(); setBusy(true)
    try { await api.saveReview(request.start_date, request.end_date, item.review.key, state, note, request.expected_revision); setMessage(en ? 'Saved' : '已保存') }
    catch (cause) { setMessage(searchError(cause, en)); setStale(true) }
    finally { setBusy(false) }
  }}>
    <h3>{item.review.rule_id === 'large_outflow_v1' ? (en ? 'Large outflow' : '大额流出') : (en ? 'Possible duplicate' : '疑似重复')}</h3>
    <details><summary>{en ? 'Evidence' : '关联证据'} · {item.evidence_total}</summary>{item.evidence.map(row => <p key={row.id}>{row.booking_date} · {row.account_name} · {row.merchant} · {row.amount} {row.currency}</p>)}
      {item.evidence_total > 20 && <nav><button type="button" disabled={busy || stale || !item.evidence_offset} onClick={() => void more(item.evidence_offset - 20)}>{en ? 'Previous evidence' : '上一页证据'}</button><button type="button" disabled={busy || stale || item.evidence_offset + 20 >= item.evidence_total} onClick={() => void more(item.evidence_offset + 20)}>{en ? 'Next evidence' : '下一页证据'}</button></nav>}
    </details>
    <label>{en ? 'Decision' : '核查状态'}<select disabled={busy || stale} value={state} onChange={e => setState(e.target.value as ReviewItem['state'])}><option value="pending">{en ? 'Pending' : '待处理'}</option><option value="normal">{en ? 'Normal' : '正常'}</option><option value="follow_up">{en ? 'Follow up' : '待进一步核实'}</option></select></label>
    <label>{en ? 'Note' : '备注'}<input disabled={busy || stale} value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label>
    <button disabled={busy || stale}>{en ? 'Save decision' : '保存结论'}</button>{message && <p role="status">{message}</p>}
  </form>
}
