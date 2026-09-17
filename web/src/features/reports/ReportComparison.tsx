/** 文件职责：按需比较同月已保存版本，金额直接读取各自冻结快照，不混入实时账务。 */
import { useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTimestamp } from '../../format'
import type { Locale } from '../../i18n'
import type { MonthlyReport, ReportDetail } from '../../types'

export function ReportComparison({
  current,
  previous,
  locale,
}: {
  current: ReportDetail
  previous: MonthlyReport
  locale: Locale
}) {
  const [older, setOlder] = useState<ReportDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const english = locale === 'en-US'
  return (
    <section className="report-comparison">
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setError(false)
          try {
            setOlder(await api.report(previous.id))
          } catch {
            setError(true)
          } finally {
            setBusy(false)
          }
        }}
      >
        {busy
          ? english
            ? 'Comparing…'
            : '正在读取版本…'
          : english
            ? 'Compare previous saved version'
            : '对比上一已保存版本'}
      </button>
      {error && (
        <p role="alert">
          {english
            ? 'Version unavailable. Retry or refresh history.'
            : '无法读取旧版本，请重试或刷新历史。'}
        </p>
      )}
      {older?.snapshot && current.snapshot && (
        <div>
          <p>
            {formatTimestamp(older.created_at, locale)} →{' '}
            {formatTimestamp(current.created_at, locale)}
          </p>
          <p>
            {english ? 'Imported transactions' : '快照流水数'}：
            {older.snapshot.review.coverage.transaction_count} →{' '}
            {current.snapshot.review.coverage.transaction_count}
          </p>
          {current.snapshot.review.adjusted_summaries.map((row) => {
            const before = older.snapshot!.review.adjusted_summaries.find(
              (item) => item.currency === row.currency,
            )
            return (
              <p key={row.currency}>
                {row.currency} · {english ? 'Spending' : '支出'}：
                {before ? formatMoney(before.adjusted_outflow, row.currency, locale) : '—'} →{' '}
                {formatMoney(row.adjusted_outflow, row.currency, locale)} ·{' '}
                {english ? 'Income' : '收入'}：
                {before ? formatMoney(before.adjusted_inflow, row.currency, locale) : '—'} →{' '}
                {formatMoney(row.adjusted_inflow, row.currency, locale)}
              </p>
            )
          })}
          {older.snapshot.review.adjusted_summaries
            .filter(
              (row) =>
                !current.snapshot!.review.adjusted_summaries.some(
                  (item) => item.currency === row.currency,
                ),
            )
            .map((row) => (
              <p key={row.currency}>
                {row.currency} ·{' '}
                {english ? 'Only present in the older snapshot' : '仅旧快照包含此币种'} ·{' '}
                {formatMoney(row.adjusted_outflow, row.currency, locale)}
              </p>
            ))}
        </div>
      )}
    </section>
  )
}
