/**
 * 文件职责：提供单个周期期次的流水核对。
 * 主要内容：候选查询、跨月选择、匹配解绑及未发生确认。
 * 关键边界：迟到查询不覆盖当前月份；关联与金额合法性由服务端校验。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Locale } from '../../i18n'
import { currentPeriod } from '../../shared/period'
import { LoadingIndicator } from '../../shared/ui'
import type { RecurringItem, RecurringTransaction } from './types'
import { planningError } from './errors'

export function Occurrence({
  item,
  due,
  transaction,
  candidates,
  locale,
  busy,
  refreshKey,
  onMatch,
  skipped,
  onSkip,
}: {
  item: RecurringItem
  due: string
  transaction: RecurringTransaction | null
  candidates: RecurringTransaction[]
  locale: Locale
  busy: boolean
  refreshKey: number
  skipped: boolean
  onSkip: (skipped: boolean) => Promise<boolean>
  onMatch: (id: string | null) => Promise<boolean>
}) {
  const today = currentPeriod().end
  const [confirmSkip, setConfirmSkip] = useState(false)
  const [selected, setSelected] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const english = locale === 'en-US'
  const [candidateMonth, setCandidateMonth] = useState(due.slice(0, 7))
  const [otherCandidates, setOtherCandidates] = useState<{
    month: string
    refreshKey: number
    rows: RecurringTransaction[]
  } | null>(null)
  const [candidateError, setCandidateError] = useState('')
  const [candidateAttempt, setCandidateAttempt] = useState(0)
  useEffect(() => {
    if (candidateMonth === due.slice(0, 7) || transaction) return
    let active = true
    setCandidateError('')
    api
      .recurringCandidates(candidateMonth)
      .then((rows) => {
        if (active) {
          setOtherCandidates({ month: candidateMonth, refreshKey, rows })
          setCandidateError('')
        }
      })
      .catch((error) => {
        if (active) setCandidateError(planningError(error, english))
      })
    return () => {
      active = false
    }
  }, [candidateMonth, due, transaction, english, candidateAttempt, refreshKey])
  const t = (zh: string, en: string) => (english ? en : zh)
  const candidatesCurrent =
    otherCandidates?.month === candidateMonth && otherCandidates.refreshKey === refreshKey
  const source =
    candidateMonth === due.slice(0, 7) ? candidates : candidatesCurrent ? otherCandidates.rows : []
  const available = source.filter(
    (row) => row.account_id === item.account_id && row.currency === item.currency,
  )
  // 同商户同金额优先，再按商户与预计日期距离排序；仍由用户确认。
  available.sort((a, b) => {
    const score = (row: typeof a) =>
      Number(row.merchant === item.merchant) * 2 +
      Number(row.amount.replace(/^-/, '') === item.amount)
    return (
      score(b) - score(a) ||
      Math.abs(Date.parse(a.booking_date) - Date.parse(due)) -
        Math.abs(Date.parse(b.booking_date) - Date.parse(due))
    )
  })
  const strongCandidate = available.find(
    (row) => row.merchant === item.merchant && row.amount.replace(/^-/, '') === item.amount,
  )
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const filtered = available.filter((row) =>
    terms.every((term) =>
      `${row.merchant} ${row.booking_date} ${row.amount}`.toLocaleLowerCase().includes(term),
    ),
  )
  const currentPage = Math.min(page, Math.max(0, Math.ceil(filtered.length / 10) - 1))
  const visible = filtered.slice(currentPage * 10, (currentPage + 1) * 10)
  const validSelection = visible.some((row) => row.id === selected) ? selected : ''
  const amountChanged = transaction && transaction.amount.replace(/^-/, '') !== item.amount
  return (
    <section className="planning-occurrence">
      <strong>
        {due} ·{' '}
        {transaction
          ? transaction.eligible
            ? t('已核对', 'Linked')
            : t('关联需重核', 'Review link')
          : skipped
            ? t('本期未发生', 'No charge this period')
            : due > today
              ? t('即将到期', 'Upcoming')
              : t('待核对', 'Unreviewed')}
      </strong>
      {skipped ? (
        <button disabled={busy} onClick={() => void onSkip(false)}>
          {t('撤回未发生确认', 'Undo confirmation')}
        </button>
      ) : transaction ? (
        <>
          <p>
            {transaction.booking_date} · {transaction.merchant} ·{' '}
            {formatMoney(transaction.amount, transaction.currency, locale)}
          </p>
          {amountChanged && (
            <p className="planning-hint">
              {t('实际金额与预计金额不同', 'Actual amount differs from the expected amount')}
            </p>
          )}
          {!transaction.eligible && (
            <p className="error">
              {t(
                '该流水已被确认为重复或本人转账，请解除并重新核对。',
                'This transaction is now a duplicate or transfer. Unlink and review.',
              )}
            </p>
          )}
          <button disabled={busy} onClick={() => void onMatch(null)}>
            {t('解除关联', 'Unlink')}
          </button>
        </>
      ) : (
        <details className="occurrence-review">
          <summary>{t('核对本期扣款', 'Review this charge')}</summary>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (validSelection && !busy) void onMatch(validSelection)
            }}
          >
            <label>
              {t('流水月份', 'Transaction month')}
              <input
                type="month"
                min="1900-01"
                max="9998-12"
                disabled={busy}
                value={candidateMonth}
                onChange={(e) => {
                  if (
                    /^\d{4}-\d{2}$/.test(e.target.value) &&
                    e.target.value >= '1900-01' &&
                    e.target.value <= '9998-12'
                  ) {
                    setCandidateMonth(e.target.value)
                    setSelected('')
                    setPage(0)
                    setCandidateError('')
                  }
                }}
              />
            </label>
            {candidateError && (
              <p className="error" role="alert">
                {candidateError}
                <button
                  type="button"
                  onClick={() => {
                    setCandidateError('')
                    setCandidateAttempt((value) => value + 1)
                  }}
                >
                  {t('重试', 'Retry')}
                </button>
              </p>
            )}
            {candidateMonth !== due.slice(0, 7) && !candidatesCurrent && !candidateError && (
              <LoadingIndicator label={t('正在读取流水', 'Loading transactions')} />
            )}
            <label>
              {t('搜索商户、日期或金额', 'Search merchant, date or amount')}
              <input
                type="search"
                value={query}
                disabled={busy}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setPage(0)
                  setSelected('')
                }}
              />
            </label>
            {(candidateMonth === due.slice(0, 7) || candidatesCurrent) && (
              <fieldset className="planning-candidates" disabled={busy}>
                <legend>
                  {t('选择实际扣款', 'Actual charge')} · {filtered.length}
                </legend>
                {visible.map((row) => (
                  <label key={row.id}>
                    <input
                      type="radio"
                      name={`charge-${item.id}-${due}`}
                      value={row.id}
                      checked={validSelection === row.id}
                      onChange={() => setSelected(row.id)}
                    />
                    <span>
                      {row.merchant === item.merchant &&
                        row.amount.replace(/^-/, '') === item.amount && (
                          <small>
                            {t('优先核对：商户和金额一致', 'Suggested: merchant and amount match')}{' '}
                            ·{' '}
                          </small>
                        )}
                      {row.booking_date} · {row.merchant} ·{' '}
                      {formatMoney(row.amount, row.currency, locale)}
                    </span>
                  </label>
                ))}
                {!filtered.length && (
                  <p>
                    {query
                      ? t('没有匹配的流水', 'No matching transactions')
                      : t('当月暂无可关联流水', 'No eligible transactions this month')}
                  </p>
                )}
              </fieldset>
            )}
            {filtered.length > 10 && (
              <div className="planning-actions">
                <button
                  type="button"
                  disabled={busy || currentPage === 0}
                  onClick={() => {
                    setPage(currentPage - 1)
                    setSelected('')
                  }}
                >
                  {t('上一页', 'Previous')}
                </button>
                <span>
                  {currentPage + 1} / {Math.ceil(filtered.length / 10)}
                </span>
                <button
                  type="button"
                  disabled={busy || (currentPage + 1) * 10 >= filtered.length}
                  onClick={() => {
                    setPage(currentPage + 1)
                    setSelected('')
                  }}
                >
                  {t('下一页', 'Next')}
                </button>
              </div>
            )}
            <button disabled={busy || !validSelection}>{t('确认关联', 'Confirm link')}</button>
            {due <= today && item.status === 'active' && (
              <button type="button" disabled={busy} onClick={() => setConfirmSkip(true)}>
                {t('本期未发生', 'No charge this period')}
              </button>
            )}
            {confirmSkip && (
              <div className="planning-confirm">
                {strongCandidate && (
                  <div>
                    <p>
                      {t(
                        '有一笔商户和金额一致的流水，请先核对：',
                        'A transaction matches the merchant and amount: ',
                      )}
                      {strongCandidate.booking_date} · {strongCandidate.merchant} ·{' '}
                      {formatMoney(strongCandidate.amount, strongCandidate.currency, locale)}
                    </p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setQuery('')
                        setPage(
                          Math.floor(
                            available.findIndex((row) => row.id === strongCandidate.id) / 10,
                          ),
                        )
                        setSelected(strongCandidate.id)
                        setConfirmSkip(false)
                      }}
                    >
                      {t('核对这笔流水', 'Review this transaction')}
                    </button>
                  </div>
                )}
                <span>
                  {t(
                    '确认本期没有发生扣款？稍后可以撤回。',
                    'Confirm no charge occurred this period? You can undo this.',
                  )}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    if (await onSkip(true)) setConfirmSkip(false)
                  }}
                >
                  {strongCandidate
                    ? t('不是这次扣款，确认未发生', 'Not this charge; confirm no charge')
                    : t('确认未发生', 'Confirm no charge')}
                </button>
                <button type="button" disabled={busy} onClick={() => setConfirmSkip(false)}>
                  {t('继续查找', 'Keep looking')}
                </button>
              </div>
            )}
          </form>
        </details>
      )}
    </section>
  )
}
