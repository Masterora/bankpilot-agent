/**
 * 文件职责：提供不依赖模型的账本查询与异常核查工作区。
 * 主要内容：期间、账户和商户筛选；来源详情、分类保存、CSV 导出与核查结论。
 * 关键边界：只显示导入流水；异常判断不改金额；日期或数据变化后重新加载证据。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Messages } from '../../i18n'
import type { ReviewItem, Transaction, TransactionCategory } from '../../types'

import { ledgerCsv } from './ledgerExport'

export function LedgerPage({ copy, english }: { copy: Messages; english: boolean }) {
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`)
  const [end, setEnd] = useState(today)
  const [items, setItems] = useState<Transaction[]>([])
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  const [account, setAccount] = useState('')
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState('')
  const invalid = !start || !end || start > end || (Date.parse(end) - Date.parse(start)) / 86400000 > 366
  useEffect(() => {
    if (invalid) return
    let active = true
    Promise.all([api.ledger(start, end), api.reviews(start, end)])
      .then(([data, review]) => { if (active) { setItems(data.items); setReviews(review.items); setState('ready') } })
      .catch(() => { if (active) setState('failed') })
    return () => { active = false }
  }, [start, end, attempt, invalid])

  async function correct(id: string, category: TransactionCategory) {
    setSaving(true); setNotice('')
    try {
      await api.correctLedgerCategory(id, category)
      setItems((current) => current.map((i) => i.id === id ? { ...i, category, category_source: 'user' } : i))
      setNotice(english ? 'Saved. Historical snapshots are unchanged.' : '已保存，历史快照保持不变。')
    } catch { setNotice(english ? 'Save failed. Retry the change.' : '保存失败，请重新选择分类。') }
    finally { setSaving(false) }
  }
  const filtered = items.filter((i) => (!account || i.account_name === account) && `${i.merchant} ${i.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const visibleIds = new Set(filtered.map((i) => i.id))
  function download() {
    const url = URL.createObjectURL(new Blob([ledgerCsv(filtered)], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = `bankpilot-${start}-${end}.csv`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="product-page">
    <header className="page-header"><h1>{english ? 'Transaction ledger' : '交易账本'}</h1><p>{english ? 'Imported flows · Coverage unverified · Not net consumption' : '已导入流水 · 期间完整性未验证 · 非净消费'}</p></header>
    <div className="import-account-grid">
      <label>{english ? 'From' : '开始日期'}<input type="date" value={start} onChange={(e) => { setState('loading'); setStart(e.target.value) }} /></label>
      <label>{english ? 'To' : '结束日期'}<input type="date" value={end} onChange={(e) => { setState('loading'); setEnd(e.target.value) }} /></label>
      <label>{english ? 'Account' : '账户'}<select value={account} onChange={(e) => setAccount(e.target.value)}><option value="">{english ? 'All accounts' : '全部账户'}</option>{[...new Set(items.map((i) => i.account_name))].map((name) => <option key={name}>{name}</option>)}</select></label>
      <label>{english ? 'Merchant or note' : '商户或备注'}<input value={search} onChange={(e) => setSearch(e.target.value)} /></label>
    </div>
    {notice && <p role="status">{notice}</p>}
    {invalid ? <p role="alert">{english ? 'Select an ordered period of at most 366 days.' : '请选择有效期间，跨度不超过 366 天。'}</p> : state === 'loading' ? <p>{english ? 'Loading' : '正在读取'}</p> : state === 'failed' ? <button onClick={() => { setState('loading'); setAttempt((a) => a + 1) }}>{english ? 'Request failed. Retry' : '读取失败，重试'}</button> : <>
      <button disabled={!filtered.length} onClick={download}>{english ? 'Export filtered CSV' : '导出筛选结果 CSV'}</button>
      {!filtered.length ? <p>{english ? 'No matching transactions' : '暂无匹配交易'}</p> : <div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Date', 'Account', 'Merchant / Source', 'Amount', 'Category'] : ['日期', '账户', '商户／来源', '金额', '分类']).map((text) => <th key={text}>{text}</th>)}</tr></thead><tbody>{filtered.map((item) => <tr key={item.id}>
        <td>{item.booking_date}</td><td>{item.account_name}</td><td>{item.merchant}<details><summary>{english ? 'Details' : '详情'}</summary><p>{item.description || '—'}</p><p>{english ? 'Batch' : '批次'}：{item.import_batch_id ?? '—'}</p><p>{english ? 'Source row' : '源行'}：{item.source_row_number ?? '—'}</p><p>{english ? 'Time precision' : '时间精度'}：{item.time_precision === 'timestamp' ? (english ? 'Timestamp' : '时间') : item.time_precision === 'date' ? (english ? 'Date' : '日期') : (english ? 'Unknown' : '未知')}</p></details></td>
        <td>{item.amount} {item.currency}</td><td><select aria-label={`${copy.categoryLabel}: ${item.merchant}`} value={item.category} disabled={saving} onChange={(e) => void correct(item.id, e.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td>
      </tr>)}</tbody></table></div>}
      <h2>{english ? 'Review' : '异常核查'}</h2><p>{english ? 'Judgments do not change amounts or confirm a bank action.' : '核查结论不改变金额，不代表银行已处理。'}</p>
      {!reviews.some((r) => r.transaction_ids.some((id) => visibleIds.has(id))) && <p>{english ? 'No rule matches in the selection' : '当前筛选未命中核查规则'}</p>}
      {reviews.filter((r) => r.transaction_ids.some((id) => visibleIds.has(id))).map((review) => <ReviewForm key={review.key} review={review} english={english} start={start} end={end} evidence={items.filter((i) => review.transaction_ids.includes(i.id))} />)}
    </>}
  </section>
}

/** 每个核查项独立保存；失败保留输入，刷新后从服务端恢复状态。 */
function ReviewForm({ review, english, start, end, evidence }: { review: ReviewItem; english: boolean; start: string; end: string; evidence: Transaction[] }) {
  const [status, setStatus] = useState(review.state)
  const [note, setNote] = useState(review.note)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  return <form className="import-report" onSubmit={async (event) => {
    event.preventDefault(); setBusy(true); setMessage('')
    try { await api.saveReview(start, end, review.key, status, note); setMessage(english ? 'Saved' : '已保存') }
    catch { setMessage(english ? 'Save failed. Reload the ledger and retry.' : '保存失败，请刷新账本后重试。') }
    finally { setBusy(false) }
  }}><h3>{review.rule_id === 'large_outflow_v1' ? (english ? 'Large outflow' : '大额流出') : (english ? 'Possible duplicate' : '疑似重复')}</h3>
    <p>{review.rule_id === 'large_outflow_v1' ? `${english ? 'Threshold' : '阈值'} ${review.facts.threshold} ${review.facts.currency}` : `${english ? 'Window (minutes)' : '时间窗口（分钟）'} ${review.facts.window_minutes}`}</p>
    {evidence.map((i) => <p key={i.id}>{i.booking_date} · {i.account_name} · {i.merchant} · {i.amount} {i.currency}</p>)}
    <label>{english ? 'Decision' : '核查状态'}<select value={status} disabled={busy} onChange={(e) => setStatus(e.target.value as ReviewItem['state'])}><option value="pending">{english ? 'Pending' : '待处理'}</option><option value="normal">{english ? 'Confirmed normal' : '确认为正常'}</option><option value="follow_up">{english ? 'Follow up' : '待进一步核实'}</option></select></label>
    <label>{english ? 'Note' : '核查备注'}<input value={note} disabled={busy} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
    <button disabled={busy}>{english ? 'Save decision' : '保存结论'}</button><p role="status">{message}</p>
  </form>
}
