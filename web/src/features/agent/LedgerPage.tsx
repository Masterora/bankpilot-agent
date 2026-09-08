/**
 * 文件职责：提供不依赖模型的账本查询与异常核查工作区。
 * 主要内容：期间、账户和商户筛选；来源详情、分类保存、CSV 导出与核查结论。
 * 关键边界：只显示导入流水；异常判断不改金额；日期或数据变化后重新加载证据。
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTransactionTime } from '../../format'
import type { Messages } from '../../i18n'
import type { ReviewItem, Transaction, TransactionCategory } from '../../types'

import { ledgerCsv } from './ledgerExport'
import { EmptyContent, PageHeader } from '../../shared/ui'
import { PeriodFilter } from '../../shared/PeriodFilter'
import { validPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'

export function LedgerPage({ copy, english, period, onPeriodChange }: { copy: Messages; english: boolean; period: ReviewPeriod; onPeriodChange: (period: ReviewPeriod) => void }) {
  const { start, end } = period
  const [items, setItems] = useState<Transaction[]>([])
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  const [account, setAccount] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<Transaction | null>(null)
  const detailDialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (selected) detailDialog.current?.showModal()
    else detailDialog.current?.close()
  }, [selected])
  const invalid = !validPeriod(period)
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
  const filtered = items.filter((i) => (!account || i.account_name === account) && (!category || i.category === category) && `${i.merchant} ${i.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const visibleIds = new Set(filtered.map((i) => i.id))
  function download() {
    const url = URL.createObjectURL(new Blob([ledgerCsv(filtered)], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = `bankpilot-${start}-${end}.csv`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="product-page ledger-page">
    <PageHeader copy={copy} page="review" />
    <dialog ref={detailDialog} className="transaction-drawer" onClose={() => setSelected(null)} onCancel={() => setSelected(null)} aria-label={english ? 'Transaction details' : '交易详情'}>
      {selected && <><header><h2>{english ? 'Transaction details' : '交易详情'}</h2><button type="button" onClick={() => setSelected(null)} aria-label={english ? 'Close' : '关闭'}>×</button></header>
      <p className="drawer-merchant">{selected.merchant}</p><strong className="drawer-amount">{formatMoney(selected.amount, selected.currency, english ? 'en-US' : 'zh-CN')}</strong>
      <dl>{[
        [english ? 'Account' : '账户', selected.account_name],
        [english ? 'Time' : '时间', formatTransactionTime(selected, english ? 'en-US' : 'zh-CN')],
        [english ? 'Note' : '备注', selected.description || '—'],
        [english ? 'Batch' : '来源批次', selected.import_batch_id ?? '—'],
        [english ? 'Source row' : '源行', selected.source_row_number ?? '—'],
        [english ? 'Time precision' : '时间精度', selected.time_precision === 'timestamp' ? (english ? 'Timestamp' : '时间') : selected.time_precision === 'date' ? (english ? 'Date' : '日期') : (english ? 'Unknown' : '未知')],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></>}
    </dialog>
    <PeriodFilter period={period} english={english} onChange={(value) => { setState('loading'); onPeriodChange(value) }} />
    <div className="ledger-filters">
      <label>{english ? 'Account' : '账户'}<select aria-label={english ? 'Account filter' : '账户筛选'} value={account} onChange={(e) => setAccount(e.target.value)}><option value="">{english ? 'All accounts' : '全部账户'}</option>{[...new Set(items.map((i) => i.account_name))].map((name) => <option key={name}>{name}</option>)}</select></label>
      <label>{english ? 'Category' : '分类'}<select aria-label={english ? 'Category filter' : '分类筛选'} value={category} onChange={(e) => setCategory(e.target.value)}><option value="">{english ? 'All categories' : '全部分类'}</option>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>{english ? 'Merchant or note' : '商户或备注'}<input value={search} onChange={(e) => setSearch(e.target.value)} /></label>
    </div>
    {notice && <p role="status">{notice}</p>}
    {invalid ? <p role="alert">{english ? 'Select an ordered period of at most 366 days.' : '请选择有效期间，跨度不超过 366 天。'}</p> : state === 'loading' ? <p>{english ? 'Loading' : '正在读取'}</p> : state === 'failed' ? <button onClick={() => { setState('loading'); setAttempt((a) => a + 1) }}>{english ? 'Request failed. Retry' : '读取失败，重试'}</button> : <>
      <div className="ledger-toolbar"><span>{filtered.length} {english ? 'transactions' : '笔交易'}</span><button disabled={!filtered.length} onClick={download}>{english ? 'Export CSV' : '导出 CSV'}</button></div>
      <div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Time', 'Account', 'Merchant / Source', 'Amount', 'Category'] : ['时间', '账户', '商户／来源', '金额', '分类']).map((text) => <th key={text}>{text}</th>)}</tr></thead><tbody>{!filtered.length && <tr><td colSpan={5}><EmptyContent kind="review" title={english ? 'No transactions to display' : '暂无可显示的流水'} detail={items.length ? (english ? 'Try clearing the filters.' : '调整筛选条件，查看其他交易。') : (english ? 'Import a statement or select another period.' : '导入账单，或选择其他期间。')}>
        {items.length ? <button onClick={() => { setAccount(''); setCategory(''); setSearch('') }}>{english ? 'Clear filters' : '清除筛选'}</button> : <a className="primary" href="#page=import">{english ? 'Import statement' : '导入账单'}</a>}
      </EmptyContent></td></tr>}{filtered.map((item) => <tr key={item.id}>
        <td className="time-cell">{formatTransactionTime(item, english ? 'en-US' : 'zh-CN')}</td><td>{item.account_name}</td><td><button className="transaction-link" onClick={() => setSelected(item)}>{item.merchant}</button></td>
        <td className="ledger-amount">{formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}</td><td><select aria-label={`${copy.categoryLabel}: ${item.merchant}`} value={item.category} disabled={saving} onChange={(e) => void correct(item.id, e.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td>
      </tr>)}</tbody></table></div>
      {filtered.length > 0 && <><h2>{english ? 'Review' : '异常核查'}</h2>
        {!reviews.some((r) => r.transaction_ids.some((id) => visibleIds.has(id))) && <p>{english ? 'No signals' : '无待核查交易'}</p>}
        {reviews.filter((r) => r.transaction_ids.some((id) => visibleIds.has(id))).map((review) => <ReviewForm key={review.key} review={review} english={english} start={start} end={end} evidence={items.filter((i) => review.transaction_ids.includes(i.id))} />)}
      </>}
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
    {evidence.map((i) => <p key={i.id}>{formatTransactionTime(i, english ? 'en-US' : 'zh-CN')} · {i.account_name} · {i.merchant} · {i.amount} {i.currency}</p>)}
    <label>{english ? 'Decision' : '核查状态'}<select value={status} disabled={busy} onChange={(e) => setStatus(e.target.value as ReviewItem['state'])}><option value="pending">{english ? 'Pending' : '待处理'}</option><option value="normal">{english ? 'Confirmed normal' : '确认为正常'}</option><option value="follow_up">{english ? 'Follow up' : '待进一步核实'}</option></select></label>
    <label>{english ? 'Note' : '核查备注'}<input value={note} disabled={busy} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
    <button disabled={busy}>{english ? 'Save decision' : '保存结论'}</button><p role="status">{message}</p>
  </form>
}
