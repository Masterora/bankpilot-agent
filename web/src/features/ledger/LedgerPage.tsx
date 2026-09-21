/**
 * 文件职责：提供不依赖模型的账本查询与异常核查工作区。
 * 主要内容：期间、账户和商户筛选；来源详情、分类保存、CSV 导出与核查结论。
 * 关键边界：只显示导入流水；异常判断不改金额；日期或数据变化后重新加载证据。
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTransactionTime } from '../../format'
import type { RecurringInput } from '../planning/types'
import { planningError } from '../planning/errors'
import type { Messages } from '../../i18n'
import type { ReviewItem, Transaction, TransactionCategory } from '../../types'

import { downloadFile } from '../../shared/download'
import { ledgerCsv } from '../../shared/ledgerExport'
import { CopyValue } from '../../shared/CopyValue'
import { EmptyContent, IconButton, LoadingIndicator, PageHeader } from '../../shared/ui'
import { PeriodFilter } from '../../shared/PeriodFilter'
import { validPeriod, monthPeriod, currentPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'

export interface LedgerEntry {
  transactionId?: string
  batchId?: string
  category?: TransactionCategory
  currency?: string
  period: ReviewPeriod
}

export function LedgerPage({ copy, english, period, onPeriodChange, active, entry, onStartRecurring, onAsk, onImport, onReviewRelation, onReturnToAssistant }: {
  onReturnToAssistant: () => void;
  copy: Messages; english: boolean; period: ReviewPeriod; onPeriodChange: (period: ReviewPeriod) => void;
  onReviewRelation: (id: string) => void; active: boolean; entry: LedgerEntry | null; onStartRecurring: (seed: RecurringInput) => void; onAsk: () => void; onImport: () => void
}) {
  const { start, end } = period
  const [batchId, setBatchId] = useState('')
  const [currency, setCurrency] = useState('')
  const [draftError, setDraftError] = useState('')
  const [preparing, setPreparing] = useState(false)
  const pendingTransaction = useRef('')
  const returnContext = useRef<{ period: ReviewPeriod; batchId: string; currency: string; category: string; account: string; search: string; scroll: number } | null>(null)
  const [canReturn, setCanReturn] = useState(false)
  const handledEntry = useRef<LedgerEntry | null>(null)

  const [items, setItems] = useState<Transaction[]>([])
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [loadedPeriod, setLoadedPeriod] = useState<ReviewPeriod | null>(null)
  const [failedKey, setFailedKey] = useState('')
  const requestKey = `${start}:${end}`
  const stale = loadedPeriod?.start !== start || loadedPeriod?.end !== end
  const failed = failedKey === requestKey
  const loading = stale && !failed
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
  useEffect(() => {
    if (!entry || handledEntry.current === entry) return
    handledEntry.current = entry
    if (entry.transactionId && !returnContext.current) {
      returnContext.current = { period, batchId, currency, category, account, search, scroll: window.scrollY }
    }
    if (!entry.transactionId) { returnContext.current = null; setCanReturn(false) }
    else setCanReturn(true)
    pendingTransaction.current = entry.transactionId ?? ''
    setSelected(null)
    setNotice('')
    setAttempt(value => value + 1)
    setBatchId(entry.batchId ?? ''); setCurrency(entry.currency ?? ''); setCategory(entry.category ?? ''); setAccount(''); setSearch('');
    onPeriodChange(entry.period)
    // A new explicit entry replaces filters; ordinary navigation preserves them.
  }, [entry, onPeriodChange, period, batchId, currency, category, account, search])
  const invalid = !validPeriod(period)
  useEffect(() => {
    if (invalid || !active) return
    if (pendingTransaction.current && entry && (start !== entry.period.start || end !== entry.period.end)) return
    let current = true
    Promise.all([api.ledger(start, end), api.reviews(start, end)])
      .then(([data, review]) => { if (current) { setItems(data.items); setReviews(review.items); setLoadedPeriod({ start, end }); setFailedKey('')
        if (pendingTransaction.current) {
          const target = data.items.find(row => row.id === pendingTransaction.current)
          pendingTransaction.current = ''
          setSelected(target ?? null)
          if (!target) setNotice(english ? 'This transaction is unavailable or was revoked.' : '该流水已不可用或已被撤销。')
        } } })
      .catch(() => { if (current) setFailedKey(requestKey) })
    return () => { current = false }
  }, [start, end, attempt, invalid, requestKey, active, entry, english])

  async function correct(id: string, category: TransactionCategory) {
    if (saving || stale) return
    setSaving(true); setNotice('')
    try {
      await api.correctLedgerCategory(id, category)
      setItems((current) => current.map((i) => i.id === id ? { ...i, category, category_source: 'user' } : i))
      setNotice(english ? 'Category saved. Budgets will use this category.' : '分类已保存，预算会按此分类统计。')
    } catch { setNotice(english ? 'Save failed. Retry the change.' : '保存失败，请重新选择分类。') }
    finally { setSaving(false) }
  }
  const filtered = items.filter((i) => (!batchId || i.import_batch_id === batchId) && (!currency || i.currency === currency) && (!account || i.account_name === account) && (!category || i.category === category) && `${i.merchant} ${i.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const visibleIds = new Set(filtered.map((i) => i.id))
  function clearFilters() { setBatchId(''); setCurrency(''); setCategory(''); setAccount(''); setSearch('') }
  const chips = [
    { label: `${start} — ${end}`, remove: () => onPeriodChange(currentPeriod()) },
    ...(batchId ? [{ label: english ? 'This import' : '本次导入', remove: () => setBatchId('') }] : []),
    ...(currency ? [{ label: currency, remove: () => setCurrency('') }] : []),
    ...(account ? [{ label: account, remove: () => setAccount('') }] : []),
    ...(category ? [{ label: copy.categoryLabels[category as TransactionCategory], remove: () => setCategory('') }] : []),
    ...(search ? [{ label: search, remove: () => setSearch('') }] : []),
  ]
  function returnToAssistant() {
    setSelected(null)
    const saved = returnContext.current
    if (saved) {
      setBatchId(saved.batchId); setCurrency(saved.currency); setCategory(saved.category)
      setAccount(saved.account); setSearch(saved.search); onPeriodChange(saved.period)
      requestAnimationFrame(() => window.scrollTo({ top: saved.scroll }))
    }
    returnContext.current = null
    pendingTransaction.current = ''
    setCanReturn(false)
    setNotice('')
    onReturnToAssistant()
  }
  function download() {
    downloadFile(ledgerCsv(filtered), `bankpilot-${start}-${end}.csv`, 'text/csv;charset=utf-8')
  }
  return <section className="product-page ledger-page">
    <div className="page-heading-actions"><PageHeader copy={copy} page="review" /><div className="planning-actions"><button onClick={onAsk}>{english ? 'Ask about this period' : '核查本期账单'}</button><button onClick={onImport}>{english ? 'Import statement' : '导入账单'}</button></div></div>
    {canReturn && <button onClick={returnToAssistant}>{english ? 'Back to assistant' : '返回助手'}</button>}
    <dialog ref={detailDialog} className="transaction-drawer" onClose={() => setSelected(null)} onCancel={() => setSelected(null)} aria-label={english ? 'Transaction details' : '交易详情'}>
      {selected && <><header><h2>{english ? 'Transaction details' : '交易详情'}</h2><IconButton icon="close" onClick={() => setSelected(null)} label={english ? 'Close' : '关闭'} /></header>
      {canReturn && <button onClick={returnToAssistant}>{english ? 'Back to assistant' : '返回助手'}</button>}
      <p className="drawer-merchant">{selected.merchant}</p><strong className="drawer-amount">{formatMoney(selected.amount, selected.currency, english ? 'en-US' : 'zh-CN')}</strong>
      {draftError && <p role="alert">{draftError}</p>}
      <label>{copy.categoryLabel}<select aria-label={english ? 'Detail category' : '详情分类'} value={items.find((row) => row.id === selected.id)?.category ?? selected.category} disabled={saving || stale} onChange={(event) => void correct(selected.id, event.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {notice && <p role="status">{notice}</p>}
      {selected.amount.startsWith('-') && <button className="primary" disabled={preparing || stale} onClick={async () => {
        setPreparing(true); setDraftError('')
        try { const seed = await api.recurringDraft(selected.id); setSelected(null); onStartRecurring(seed) }
        catch (error) { setDraftError(planningError(error, english)) }
        finally { setPreparing(false) }
      }}>{english ? 'Create a fixed expense' : '设为固定支出'}</button>}
      <button disabled={stale} onClick={() => { const id = selected.id; setSelected(null); onReviewRelation(id) }}>{english ? 'Review transfer, refund or duplicate' : '核对转账、退款或重复'}</button>
      <dl><div><dt>{english ? 'ID' : '交易标识'}</dt><dd><CopyValue value={selected.id} english={english} /></dd></div>{[
        [english ? 'Account' : '账户', selected.account_name],
        [english ? 'Time' : '时间', formatTransactionTime(selected, english ? 'en-US' : 'zh-CN')],
        [english ? 'Note' : '备注', selected.description || '—'],
        [english ? 'Batch' : '来源批次', selected.import_batch_id ?? '—'],
        [english ? 'Source row' : '源行', selected.source_row_number ?? '—'],
        [english ? 'Time precision' : '时间精度', selected.time_precision === 'timestamp' ? (english ? 'Timestamp' : '时间') : selected.time_precision === 'date' ? (english ? 'Date' : '日期') : (english ? 'Unknown' : '未知')],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{label === (english ? 'Batch' : '来源批次') && selected.import_batch_id ? <CopyValue value={selected.import_batch_id} english={english} /> : value}</dd></div>)}</dl></>}
    </dialog>
    <details className="ledger-filter-panel"><summary>{english ? 'Filters & date range' : '筛选与日期'} · {start} — {end}</summary>
    <PeriodFilter period={period} english={english} onChange={onPeriodChange} />
    <div className="ledger-filters">
      <label>{english ? 'Account' : '账户'}<select aria-label={english ? 'Account filter' : '账户筛选'} value={account} onChange={(e) => setAccount(e.target.value)}><option value="">{english ? 'All accounts' : '全部账户'}</option>{[...new Set(items.map((i) => i.account_name))].map((name) => <option key={name}>{name}</option>)}</select></label>
      <label>{english ? 'Category' : '分类'}<select aria-label={english ? 'Category filter' : '分类筛选'} value={category} onChange={(e) => setCategory(e.target.value)}><option value="">{english ? 'All categories' : '全部分类'}</option>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>{english ? 'Merchant or note' : '商户或备注'}<input value={search} onChange={(e) => setSearch(e.target.value)} /></label>
    </div>
    </details>
    <div className="filter-chips" aria-label={english ? 'Active filters' : '当前筛选'}>{chips.map((chip, index) => <button key={index} onClick={chip.remove} aria-label={`${english ? 'Remove filter' : '移除筛选'}: ${chip.label}`}>{chip.label} ×</button>)}<button onClick={() => { clearFilters(); onPeriodChange(currentPeriod()) }}>{english ? 'Reset all' : '重置全部'}</button>{batchId && <button onClick={() => { clearFilters(); onPeriodChange(monthPeriod(start.slice(0, 7))!) }}>{english ? 'View full month' : '返回整月账本'}</button>}</div>
    {notice && <p role="status">{notice}</p>}
    {invalid ? null : <div className="ledger-data" aria-busy={loading}>
      {loading && <LoadingIndicator label={english ? 'Loading ledger' : '正在读取账本'} />}
      {failed && <p className="error" role="alert">{english ? 'Could not update ledger.' : '账本更新失败。'} <button onClick={() => { setFailedKey(''); setAttempt((a) => a + 1) }}>{english ? 'Retry' : '重试'}</button></p>}
      {loadedPeriod && <>
      {stale && <p className="overview-retained-period">{english ? 'Displayed period' : '当前显示期间'}：{loadedPeriod.start} — {loadedPeriod.end}</p>}
      <div className="ledger-toolbar"><span>{filtered.length} {english ? 'transactions' : '笔交易'}</span><button disabled={!filtered.length || stale} onClick={download}>{english ? 'Export CSV' : '导出 CSV'}</button></div>
      <div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Time', 'Account', 'Merchant / Source', 'Amount', 'Category'] : ['时间', '账户', '商户／来源', '金额', '分类']).map((text) => <th scope="col" key={text}>{text}</th>)}</tr></thead><tbody>{!filtered.length && <tr><td colSpan={5}><EmptyContent kind="review" title={english ? 'No transactions to display' : '暂无可显示的流水'} detail={items.length ? (english ? 'Try clearing the filters.' : '调整筛选条件，查看其他交易。') : (english ? 'Import a statement or select another period.' : '导入账单，或选择其他期间。')}>
        {items.length ? <button onClick={clearFilters}>{english ? 'Clear filters' : '清除筛选'}</button> : <button className="primary" onClick={onImport}>{english ? 'Import statement' : '导入账单'}</button>}
      </EmptyContent></td></tr>}{filtered.map((item) => <tr key={item.id}>
        <td className="time-cell">{formatTransactionTime(item, english ? 'en-US' : 'zh-CN')}</td><td>{item.account_name}</td><td><button className="transaction-link" onClick={() => setSelected(item)}>{item.merchant}</button>{item.description && <small className="ledger-note">{item.description}</small>}</td>
        <td className={`ledger-amount${Number(item.amount) >= 0 ? ' income' : ''}`}>{formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}</td><td><select aria-label={`${copy.categoryLabel}: ${item.merchant}`} value={item.category} disabled={saving || stale} onChange={(e) => void correct(item.id, e.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="mobile-category">{copy.categoryLabels[item.category]}</span></td>
      </tr>)}</tbody></table></div>
      {!stale && reviews.some((r) => r.transaction_ids.some((id) => visibleIds.has(id))) && <><h2>{english ? 'Review' : '异常核查'}</h2>
        {reviews.filter((r) => r.transaction_ids.some((id) => visibleIds.has(id))).map((review) => <ReviewForm key={`${start}:${end}:${review.key}`} review={review} english={english} start={start} end={end} evidence={items.filter((i) => review.transaction_ids.includes(i.id))} />)}
      </>}
    </>}
    </div>}
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
