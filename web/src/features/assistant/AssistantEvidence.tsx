/** 按工具展示服务端原始统计；证据折叠，金额不由模型重算。 */
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { spendingRefs } from './types'
import type { Evidence, SpendingSummary } from './types'
import { SpendingCard } from './SpendingDetails'
export function AssistantEvidence({
  evidence,
  copy,
  locale,
  stale,
  onInspect,
}: {
  evidence: Evidence[]
  copy: Messages
  locale: Locale
  stale: boolean
  onInspect: (summary: SpendingSummary) => void
}) {
  const en = locale === 'en-US'
  const money = (value: string, currency: string) => formatMoney(value, currency, locale)
  const otherEvidence = evidence.filter(item => item.tool !== 'spending')
  return (
    evidence.length > 0 && (
      <>
      {spendingRefs(evidence).map((summary, index) => <div key={index}>
        <SpendingCard summary={summary} copy={copy} locale={locale} />
        {stale && <p role="status">{en ? 'Ledger changed; query again.' : '账本已更新，需要重新查询。'}</p>}
        <button onClick={() => onInspect(summary)}>{en ? 'View breakdown' : '查看构成'}</button>
      </div>)}
      {otherEvidence.length > 0 && <details className="assistant-evidence">
        <summary>
          {en ? 'Data used' : '查询依据'} · {otherEvidence.length}
        </summary>
        {otherEvidence.map((item, index) => (
          <section key={index}>
            <h4>
              {item.month.slice(0, 7)} ·{' '}
              {item.tool === 'budgets'
                ? en
                  ? 'Budgets'
                  : '预算'
                : item.tool === 'recurring'
                  ? en
                    ? 'Recurring costs'
                    : '固定支出'
                  : en
                    ? 'Income & spending'
                    : '收支'}
            </h4>
            {item.tool === 'budgets' && (
              <>
                <dl>
                  {item.data.items.map((row) => (
                    <div key={`limit:${row.category}:${row.currency}`}>
                      <dt>
                        {copy.categoryLabels[row.category]} · {en ? 'Budget' : '预算'}
                      </dt>
                      <dd>{money(row.amount, row.currency)}</dd>
                    </div>
                  ))}
                  {item.data.spending.map((row) => (
                    <div key={`${row.category}:${row.currency}`}>
                      <dt>
                        {copy.categoryLabels[row.category]} · {row.currency}
                      </dt>
                      <dd>{money(row.spent, row.currency)}</dd>
                    </div>
                  ))}
                </dl>
                {item.data.coverage.map((row) => (
                  <p key={row.currency}>
                    {row.currency} · {row.transaction_count} {en ? 'transactions' : '笔流水'} ·{' '}
                    {en ? 'Through' : '截至'} {row.latest_transaction_date ?? '—'}
                  </p>
                ))}
              </>
            )}
            {item.tool === 'overview' && (
              <dl>
                {item.data.summaries.map((row) => (
                  <div key={row.currency}>
                    <dt>{row.currency}</dt>
                    <dd>
                      {en ? 'Spending' : '支出'} {money(row.adjusted_outflow, row.currency)} ·{' '}
                      {en ? 'Income' : '收入'} {money(row.adjusted_inflow, row.currency)}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {item.tool === 'recurring' && (
              <dl>
                {item.data.items.map((row) => (
                  <div key={row.id}>
                    <dt>{row.name}</dt>
                    <dd>
                      {money(row.amount, row.currency)} · {row.next_due_date ?? '—'}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}
      </details>}
      </>
    )
  )
}
