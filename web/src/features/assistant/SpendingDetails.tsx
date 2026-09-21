/** 消费证据只读视图：分页重新校验版本，迟到响应不能覆盖当前页。 */
import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { apiErrorMessage } from '../../shared/apiErrors'
import { LoadingIndicator } from '../../shared/ui'
import type { EvidenceTarget, SpendingPage, SpendingSummary } from './types'

export function SpendingCard({ summary, copy, locale }: {
  summary: SpendingSummary; copy: Messages; locale: Locale
}) {
  const en = locale === 'en-US'
  const money = (value: string) => formatMoney(value, summary.scope.currency, locale)
  return <section className="spending-card">
    <h3>{summary.scope.month.slice(0, 7)} · {copy.categoryLabels[summary.scope.category]} · {summary.scope.currency}</h3>
    <strong>{en ? 'Net spending' : '实际支出'} {money(summary.net_spending)}</strong>
    <p>{en ? 'Purchases' : '消费'} {money(summary.gross_spending)} − {en ? 'Confirmed refunds' : '已确认退款'} {money(summary.refund_offset)}</p>
    <p>{summary.contribution_count} {en ? 'contributions' : '条贡献记录'}</p>
    <p>{summary.coverage.transaction_count === 0
      ? (en ? 'No imported data in this currency.' : '该币种尚无已导入数据。')
      : `${en ? 'Imported transactions' : '本币种已导入流水'} ${summary.coverage.transaction_count} · ${en ? 'Through' : '截至'} ${summary.coverage.latest_transaction_date}`}
      {' · '}{en ? 'Completeness unverified' : '账单完整性未确认'}</p>
    {summary.coverage.transaction_count > 0 && summary.contribution_count === 0 && <p>{en ? 'No contributions in this category in imported data.' : '已导入数据中该分类为 0。'}</p>}
  </section>
}

export function SpendingDetails({ summary, copy, locale, active, stale, onBack, onRequery, onInspect }: {
  summary: SpendingSummary; copy: Messages; locale: Locale; active: boolean; stale: boolean
  onBack: () => void; onRequery: () => void; onInspect: (target: EvidenceTarget) => void
}) {
  const [page, setPage] = useState(1)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<SpendingPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expired, setExpired] = useState(false)
  const en = locale === 'en-US'
  useEffect(() => {
    if (!active || stale || expired) return
    let current = true
    setLoading(true)
    setResult(null)
    setError('')
    api.spendingEvidence(summary, page).then(data => {
      if (current) setResult(data)
    }).catch(cause => {
      if (!current) return
      if (cause instanceof ApiError && cause.code === 'assistant_evidence_stale') setExpired(true)
      else setError(apiErrorMessage(cause, en))
    }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [summary, page, attempt, active, stale, expired, en])
  const invalid = stale || expired
  return <div className="spending-details">
    <button onClick={onBack}>{en ? 'Back to answer' : '返回回答'}</button>
    <SpendingCard summary={summary} copy={copy} locale={locale} />
    {invalid ? <p role="status">{en ? 'Ledger or calculation rules changed. Query again.' : '账本或计算规则已更新，请重新查询。'} <button onClick={onRequery}>{en ? 'Query again' : '重新查询'}</button></p>
      : loading || (result !== null && result.page !== page) ? <LoadingIndicator label={en ? 'Checking evidence' : '正在核对证据版本'} />
      : error ? <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>{en ? 'Retry' : '重试'}</button></p>
      : result && <>
        <ol className="spending-entries">
          {result.items.map(row => <li key={row.transaction_id}>
            <div><strong>{row.merchant}</strong><strong>{formatMoney(row.contribution, row.currency, locale)}</strong></div>
            <p>{row.booking_date} · {row.account_name} · {en ? 'Contribution to this month' : '对本月支出的贡献'}</p>
            <button onClick={() => onInspect({ id: row.transaction_id, booking_date: row.booking_date })}>{en ? 'Open transaction' : '查看流水'}</button>
            {row.purchase && <details><summary>{en ? 'Original purchase for this refund' : '退款对应原消费'}</summary>
              <p>{row.purchase.booking_date} · {row.purchase.merchant} · {row.purchase.account_name} · {formatMoney(row.purchase.amount, row.currency, locale)}</p>
              <p>{en ? 'Reference only; not added to this month again.' : '仅作为退款依据，不再次计入本月。'}</p>
              <button onClick={() => onInspect({ id: row.purchase!.id, booking_date: row.purchase!.booking_date })}>{en ? 'Open original purchase' : '查看原消费'}</button>
            </details>}
          </li>)}
        </ol>
        {!result.items.length && <p>{en ? 'No contribution records on this page.' : '本页没有贡献记录。'}</p>}
        <div className="planning-actions">
          <button disabled={page === 1} onClick={() => setPage(value => value - 1)}>{en ? 'Previous' : '上一页'}</button>
          <span>{page} / {Math.max(1, Math.ceil(result.total / result.page_size))}</span>
          <button disabled={page * result.page_size >= result.total} onClick={() => setPage(value => value + 1)}>{en ? 'Next' : '下一页'}</button>
        </div>
      </>}
  </div>
}
