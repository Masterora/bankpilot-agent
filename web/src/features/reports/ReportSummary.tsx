/** 文件职责：将冻结月报快照呈现为阅读与打印摘要；不重算金额或混入原始分类统计。 */
import { formatMoney, formatTimestamp } from '../../format'
import type { Locale } from '../../i18n'
import type { ReportDetail } from '../../types'

export function ReportSummary({ report, locale }: { report: ReportDetail; locale: Locale }) {
  const snapshot = report.snapshot
  if (!snapshot) return null
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const pending = snapshot.review.relations.filter((item) => item.state === 'pending').length
  const largeIds = new Set(
    snapshot.analysis.anomalies
      .filter((item) => item.rule_id === 'large_outflow_v1')
      .flatMap((item) => item.transaction_ids),
  )
  const large = largeIds.size
  const latestDate = snapshot.transactions.items
    .map((item) => item.booking_date)
    .sort()
    .at(-1)
  return (
    <section className="report-readable">
      <h2>{report.month.slice(0, 7)}</h2>
      <p className="report-meta">
        {snapshot.review.coverage.transaction_count} {t('笔流水', 'transactions')} ·{' '}
        {t('截至', 'Through')} {latestDate ?? '—'}
      </p>
      <p className="report-meta">{t('生成于', 'Generated')} {formatTimestamp(report.completed_at ?? report.created_at, locale)}</p>
      {report.stale && (
        <p>
          {t(
            '账本已更新 · 当前为已保存版本',
            'The ledger has changed since generation. These are the saved results.',
          )}
        </p>
      )}
      <div className="summary-grid">
        {snapshot.review.adjusted_summaries.map((summary) => (
          <article className="currency-summary" key={summary.currency}>
            <h3>{summary.currency}</h3>
            <dl>
              <div>
                <dt>{t('实际支出', 'Spending')}</dt>
                <dd>{formatMoney(summary.adjusted_outflow, summary.currency, locale)}</dd>
              </div>
              <div>
                <dt>{t('收入', 'Income')}</dt>
                <dd>{formatMoney(summary.adjusted_inflow, summary.currency, locale)}</dd>
              </div>
              <div>
                <dt>{t('收支净额', 'Net flow')}</dt>
                <dd>{formatMoney(summary.adjusted_net, summary.currency, locale)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      {!!large && (
        <details className="report-signals">
          <summary>
            {t('大额流水', 'View large raw outflows')} · {large}
          </summary>
          <p>
            {t(
              '以下为原始流水提示，可能包含已确认转账或重复，请结合冻结关系判断。',
              'Raw signals may include confirmed transfers or duplicates; review the saved relationships.',
            )}
          </p>
          {snapshot.transactions.items
            .filter((item) => largeIds.has(item.id))
            .map((item) => (
              <p key={item.id}>
                {item.booking_date} · {item.merchant} · {item.account_name} ·{' '}
                {formatMoney(item.amount, item.currency, locale)} ·{' '}
                {item.description || t('无备注', 'No note')}
              </p>
            ))}
        </details>
      )}
      {!!pending && (
        <details className="report-signals">
          <summary>
            {t('待核对关系', 'View pending relationships')} · {pending}
          </summary>
          {snapshot.review.relations
            .filter((item) => item.state === 'pending')
            .map((item) => (
              <article key={`${item.kind}:${item.first_id}:${item.second_id}`}>
                <h3>
                  {
                    {
                      refund: t('退款', 'Refund'),
                      duplicate: t('重复记录', 'Duplicate'),
                      transfer: t('本人转账', 'Own transfer'),
                    }[item.kind]
                  }
                </h3>
                {snapshot.review.evidence
                  .filter((row) => row.id === item.first_id || row.id === item.second_id)
                  .map((row) => (
                    <p key={row.id}>
                      {row.booking_date} · {row.merchant} · {row.account_name} ·{' '}
                      {formatMoney(row.amount, row.currency, locale)}
                    </p>
                  ))}
              </article>
            ))}
        </details>
      )}
      {snapshot.review.candidates_truncated && (
        <p>
          {t(
            '候选未全部列出，请缩小期间继续核对。',
            'Candidates are incomplete. Review a narrower period.',
          )}
        </p>
      )}
      <p className="planning-hint">
        {t(
          '仅包含已导入数据，不代表完整账期或银行余额。',
          'Imported data only; this is not proof of a complete statement period or bank balance.',
        )}
      </p>
    </section>
  )
}
