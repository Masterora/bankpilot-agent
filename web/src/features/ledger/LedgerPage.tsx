/**
 * 文件职责：提供确定性账本搜索与异常核查工作区。
 * 主要内容：筛选草稿和已执行条件、稳定分页、带版本详情、分类修正、完整 CSV 导出及核查投影。
 * 关键边界：金额与总数来自服务端；过期结果不可继续写入，草稿不直接写入 URL。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTransactionTime } from '../../format'
import type { RecurringInput } from '../planning/types'
import { planningError } from '../planning/errors'
import type { Messages } from '../../i18n'
import type { Transaction, TransactionCategory } from '../../types'

import { downloadFile } from '../../shared/download'
import { CopyValue, EmptyContent, IconButton, LoadingIndicator, PageHeader } from '../../shared/ui'
import { currentPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'

import { SearchForm } from './SearchForm'
import { useTransactionSearch } from './useTransactionSearch'
import { periodFilters, readSearch, writeSearch, searchError, versions, searchChips } from './search'
import type { SearchFilters, SearchPage } from './search'
import { LedgerReviews } from './LedgerReviews'

export interface LedgerEntry {
  transactionId?: string; batchId?: string; category?: TransactionCategory; currency?: string
  filters?: SearchFilters; version?: { expected_revision: number; expected_search_version: string }
  period: ReviewPeriod
}

export function LedgerPage({ copy, english, period, onPeriodChange, active, entry, onStartRecurring, onAsk, onImport, onReviewRelation, onReturnToAssistant }: {
  onReturnToAssistant: () => void;
  copy: Messages; english: boolean; period: ReviewPeriod; onPeriodChange: (period: ReviewPeriod) => void;
  onReviewRelation: (id: string) => void; active: boolean; entry: LedgerEntry | null; onStartRecurring: (seed: RecurringInput) => void; onAsk: () => void; onImport: () => void
}) {
  const { start, end } = period
  const [filters, setFilters] = useState(() => readSearch(period))
  const search = useTransactionSearch(active)
  const { page, busy: loading, query } = search
  const items = page?.items ?? []
  const stale = search.stale || loading
  const [selected, setSelected] = useState<Transaction | null>(null)
  const [detailRevision, setDetailRevision] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const [draftError, setDraftError] = useState('')
  const [notice, setNotice] = useState('')
  const [canReturn, setCanReturn] = useState(false)
  const [reviewsOpen, setReviewsOpen] = useState(false)
  const detailDialog = useRef<HTMLDialogElement>(null)
  const handledEntry = useRef<LedgerEntry | null>(null)
  const returnContext = useRef<{ page: SearchPage | null; filters: SearchFilters; scroll: number } | null>(null)
  const detailEpoch = useRef(0)
  useEffect(() => { if (selected) detailDialog.current?.showModal(); else detailDialog.current?.close() }, [selected])
  useEffect(() => { const clear = () => { detailEpoch.current++; setSelected(null) }; window.addEventListener('bankpilot-logout', clear); return () => { clear(); window.removeEventListener('bankpilot-logout', clear) } }, [])
  useEffect(() => {
    if (!active) { detailEpoch.current++; setSelected(null); return }
    const next = readSearch({ start, end })
    setFilters(next)
    void query(next)
    const restore = () => { detailEpoch.current++; const value = readSearch({ start, end }); setFilters(value); setSelected(null); void query(value) }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [active, start, end, query])
  const execute = useCallback(async (next: SearchFilters) => {
    detailEpoch.current++; setFilters(next); setSelected(null); setNotice(''); setReviewsOpen(false)
    writeSearch(next)
    if (next.start_date !== start || next.end_date !== end) onPeriodChange({ start: next.start_date, end: next.end_date })
    else await query(next)
  }, [start, end, onPeriodChange, query])
  const inspect = useCallback(async (id: string, version?: LedgerEntry['version']) => {
    const epoch = ++detailEpoch.current
    try {
      const result = await api.transaction(id, version)
      if (epoch !== detailEpoch.current) return
      setSelected(result.item); setDetailRevision(result.ledger_revision)
    } catch (cause) { if (epoch === detailEpoch.current) setNotice(searchError(cause, english)) }
  }, [english])
  useEffect(() => {
    if (!entry || handledEntry.current === entry) return
    handledEntry.current = entry
    if (entry.transactionId) {
      if (!returnContext.current) returnContext.current = { page, filters, scroll: window.scrollY }
      setCanReturn(true)
      void inspect(entry.transactionId, entry.version)
    } else {
      setCanReturn(false); returnContext.current = null
      void execute(entry.filters ?? { ...periodFilters(entry.period), import_batch_id: entry.batchId, category: entry.category, currency: entry.currency })
    }
  }, [entry, page, filters, inspect, execute])
  async function correct(id: string, category: TransactionCategory) {
    const revision = selected?.id === id ? detailRevision : page?.ledger_revision
    if (saving || stale || revision == null) return
    setSaving(true); setNotice('')
    try {
      await api.correctLedgerCategory(id, category, revision)
      setSelected(null); await query(filters)
    } catch (cause) {
      setNotice(searchError(cause, english))
      setDraftError(`${copy.categoryLabel}: ${copy.categoryLabels[category]}`)
      // Re-read facts but never replay the rejected write.
      await inspect(id)
    } finally { setSaving(false) }
  }
  function clearFilters() { void execute(periodFilters(period)) }
  function returnToAssistant() {
    detailEpoch.current++; setSelected(null); setCanReturn(false)
    const saved = returnContext.current
    if (saved) {
      setFilters(saved.filters)
      if (saved.page) void query(saved.filters, saved.page.offset, saved.page)
      requestAnimationFrame(() => window.scrollTo({ top: saved.scroll }))
    }
    returnContext.current = null; onReturnToAssistant()
  }
  async function download() {
    if (!page) return
    setPreparing(true)
    try { downloadFile(await api.searchExport(page), `bankpilot-${start}-${end}.csv`, 'text/csv;charset=utf-8') }
    catch (cause) { setNotice(searchError(cause, english)) }
    finally { setPreparing(false) }
  }
  return <section className="product-page ledger-page">
    <div className="page-heading-actions"><PageHeader copy={copy} page="review" /><div className="planning-actions"><button onClick={onAsk}>{english ? 'Review this period' : '核查本期账单'}</button><button onClick={onImport}>{english ? 'Import statement' : '导入账单'}</button></div></div>
    {canReturn && <button onClick={returnToAssistant}>{english ? 'Back to assistant' : '返回助手'}</button>}
    <dialog ref={detailDialog} className="transaction-drawer" onClose={() => setSelected(null)} onCancel={() => setSelected(null)} aria-label={english ? 'Transaction details' : '交易详情'}>
      {selected && <><header><h2>{english ? 'Transaction details' : '交易详情'}</h2><IconButton icon="close" onClick={() => setSelected(null)} label={english ? 'Close' : '关闭'} /></header>
      {canReturn && <button onClick={returnToAssistant}>{english ? 'Back to assistant' : '返回助手'}</button>}
      <p className="drawer-merchant">{selected.merchant}</p><strong className="drawer-amount">{formatMoney(selected.amount, selected.currency, english ? 'en-US' : 'zh-CN')}</strong>
      {draftError && <p role="alert">{draftError}</p>}
      <label>{copy.categoryLabel}<select aria-label={english ? 'Detail category' : '详情分类'} value={selected.category} disabled={saving || stale} onChange={(event) => void correct(selected.id, event.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
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
    <SearchForm key={JSON.stringify(filters)} initial={filters} copy={copy} english={english} busy={loading} onSearch={next => void execute(next)} />
    <div className="filter-chips" aria-label={english ? 'Executed filters' : '已执行条件'}>
      {page && searchChips(page.filters, copy.categoryLabels, english).map(({ key, label }) => <button key={key} onClick={() => void execute({ ...page.filters, ...(key === 'currency' ? { min_amount: null, max_amount: null } : {}), [key]: key === 'text' ? '' : key === 'direction' ? 'all' : key === 'text_scope' ? 'merchant_or_note' : null })}>{label} ×</button>)}
      <button onClick={clearFilters}>{english ? 'Clear filters' : '清除筛选'}</button><button onClick={() => void execute(periodFilters(currentPeriod()))}>{english ? 'Current month' : '本月'}</button>
    </div>
    {loading && <LoadingIndicator label={english ? 'Searching' : '查询中'} />}
    {Boolean(search.error) && <p role="alert">{searchError(search.error, english)} <button onClick={() => void query(filters)}>{english ? 'Retry' : '重试'}</button></p>}
    {notice && <p role="status">{notice}</p>}
    {search.stale && !search.error && <p role="status">{english ? 'Ledger updated.' : '账本已更新。'} <button onClick={() => void query(filters)}>{english ? 'Query again' : '重新查询'}</button></p>}
    {page && <>
      <p>{page.filters.start_date} — {page.filters.end_date}</p>
      <div className="ledger-toolbar"><span>{english ? `${page.total_count} transactions` : `共 ${page.total_count} 笔`}</span><button disabled={!page.total_count || stale || preparing} onClick={() => void download()}>{english ? 'Export CSV' : '导出 CSV'}</button></div>
      <div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Time', 'Account', 'Merchant / Source', 'Amount', 'Category'] : ['时间', '账户', '商户／来源', '金额', '分类']).map((text) => <th scope="col" key={text}>{text}</th>)}</tr></thead><tbody>{!items.length && <tr><td colSpan={5}><EmptyContent kind="review" title={english ? 'No transactions to display' : '暂无可显示的流水'} detail={items.length ? (english ? 'Try clearing the filters.' : '请调整筛选条件。') : (english ? 'Import a statement or select another period.' : '导入账单，或选择其他期间。')}>
        {items.length ? <button onClick={clearFilters}>{english ? 'Clear filters' : '清除筛选'}</button> : <button className="primary" onClick={onImport}>{english ? 'Import statement' : '导入账单'}</button>}
      </EmptyContent></td></tr>}{items.map((item) => <tr key={item.id}>
        <td className="time-cell">{formatTransactionTime(item, english ? 'en-US' : 'zh-CN')}</td><td>{item.account_name}</td><td><button className="transaction-link" onClick={() => void inspect(item.id, versions(page))}>{item.merchant}</button>{'relation_kinds' in item && (item.relation_kinds as string[]).map(kind => <small key={kind}>{english ? kind : ({ refund: '已确认退款', transfer: '已确认转账', duplicate: '已确认重复' }[kind])}</small>)}{item.description && <small className="ledger-note">{item.description}</small>}</td>
        <td className={`ledger-amount${Number(item.amount) >= 0 ? ' income' : ''}`}>{formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}</td><td><select aria-label={`${copy.categoryLabel}: ${item.merchant}`} value={item.category} disabled={saving || stale} onChange={(e) => void correct(item.id, e.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="mobile-category">{copy.categoryLabels[item.category]}</span></td>
      </tr>)}</tbody></table></div>
      {page.total_count > 0 && <nav className="planning-actions" aria-label={english ? 'Result pages' : '结果分页'}><button disabled={stale || !page.offset} onClick={() => void query(page.filters, page.offset - 20, page)}>{english ? 'Previous' : '上一页'}</button><span>{page.offset / 20 + 1} / {Math.ceil(page.total_count / 20)}</span><button disabled={stale || !page.has_more} onClick={() => void query(page.filters, page.offset + 20, page)}>{english ? 'Next' : '下一页'}</button></nav>}
      <button aria-expanded={reviewsOpen} disabled={stale} onClick={() => setReviewsOpen(value => !value)}>{english ? 'Review exceptions' : '异常核查'}</button>
      {reviewsOpen && !stale && <LedgerReviews key={`${page.ledger_revision}:${page.offset}:${JSON.stringify(page.filters)}`} page={page} period={period} english={english} />}
    </>}
  </section>
}
