/** 文件职责：读取绑定助手轮次的双月分类证据，并保护分页和迟到响应。 */
import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { apiErrorMessage } from '../../shared/apiErrors'
import { LoadingIndicator } from '../../shared/ui'
import type { ComparisonEvidencePage, EvidenceTarget, SpendingCategoryComparison } from './types'

export function ComparisonEvidenceDetails({ turnId, side, category, copy, locale, active, stale, onBack, onRecompare, onInspect }: {
  turnId: string
  side: 'baseline' | 'target'
  category: SpendingCategoryComparison['category']
  copy: Messages
  locale: Locale
  active: boolean
  stale: boolean
  onBack: () => void
  onRecompare: () => void
  onInspect: (target: EvidenceTarget) => void
}) {
  const [page, setPage] = useState(1)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<ComparisonEvidencePage | null>(null)
  const [loading, setLoading] = useState(true)
  const [expired, setExpired] = useState(false)
  const [error, setError] = useState('')
  const en = locale === 'en-US'
  useEffect(() => {
    if (!active || stale || expired) return
    let current = true
    setLoading(true); setResult(null); setError('')
    api.comparisonEvidence(turnId, side, category, page).then(value => { if (current) setResult(value) }).catch(cause => {
      if (!current) return
      if (cause instanceof ApiError && cause.code === 'assistant_evidence_stale') setExpired(true)
      else setError(apiErrorMessage(cause, en))
    }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [turnId, side, category, page, attempt, active, stale, expired, en])
  const invalid = stale || expired
  const comparison = result?.comparison
  const period = comparison ? (side === 'baseline' ? comparison.baseline : comparison.target) : null
  return <div className="spending-details comparison-details">
    <button onClick={onBack}>{en ? 'Back to comparison' : '返回比较结果'}</button>
    <h3>{copy.categoryLabels[category]} · {period ? `${period.start_date}—${period.end_date}` : ''}</h3>
    {invalid ? <p role="status">{en ? 'Ledger or calculation rules changed. Recompare to open evidence.' : '账本或计算规则已更新，请重新比较后查看构成。'} <button onClick={onRecompare}>{en ? 'Recompare' : '重新比较'}</button></p>
      : loading || (result !== null && result.page !== page) ? <LoadingIndicator label={en ? 'Checking comparison evidence' : '正在核对比较证据'} />
      : error ? <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>{en ? 'Retry' : '重试'}</button></p>
      : result && <>
        <ol className="spending-entries">
          {result.items.map(row => <li key={row.transaction_id}>
            <div><strong>{row.merchant}</strong><strong>{formatMoney(row.contribution, row.currency, locale)}</strong></div>
            <p>{row.booking_date} · {row.account_name}</p>
            <button onClick={() => onInspect({ id: row.transaction_id, booking_date: row.booking_date })}>{en ? 'Open transaction' : '查看流水'}</button>
            {row.purchase && <details><summary>{en ? 'Original purchase for this refund' : '退款对应原消费'}</summary>
              <p>{row.purchase.booking_date} · {row.purchase.merchant} · {formatMoney(row.purchase.amount, row.currency, locale)}</p>
              <button onClick={() => onInspect({ id: row.purchase!.id, booking_date: row.purchase!.booking_date })}>{en ? 'Open original purchase' : '查看原消费'}</button>
            </details>}
          </li>)}
        </ol>
        <div className="planning-actions">
          <button disabled={page === 1} onClick={() => setPage(value => value - 1)}>{en ? 'Previous' : '上一页'}</button>
          <span>{page} / {Math.max(1, Math.ceil(result.total / result.page_size))}</span>
          <button disabled={page * result.page_size >= result.total} onClick={() => setPage(value => value + 1)}>{en ? 'Next' : '下一页'}</button>
        </div>
      </>}
  </div>
}
