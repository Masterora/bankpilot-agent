/**
 * 文件职责：按助手工具类型展示服务端证据。
 * 主要内容：预算、周期项、总览、消费及交易搜索结果和证据下钻入口。
 * 关键边界：金额与事实来自服务端工具结果，不由模型文本重算或拼造。
 */
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
  onOpenDiscovery,
}: {
  evidence: Evidence[]
  copy: Messages
  locale: Locale
  stale: boolean
  onInspect: (summary: SpendingSummary) => void
  onOpenDiscovery: (through: string) => void
}) {
  const en = locale === 'en-US'
  const money = (value: string, currency: string) => formatMoney(value, currency, locale)
  const otherEvidence = evidence.filter(item => item.tool !== 'spending' && item.tool !== 'find_transactions' && item.tool !== 'compare_spending' && item.tool !== 'recurring_discovery')
  return (
    evidence.length > 0 && (
      <>
      {spendingRefs(evidence).map((summary, index) => <div key={index}>
        <SpendingCard summary={summary} copy={copy} locale={locale} />
        {stale && <p role="status">{en ? 'Ledger changed; query again.' : '账本已更新，需要重新查询。'}</p>}
        <button onClick={() => onInspect(summary)}>{en ? 'View breakdown' : '查看构成'}</button>
      </div>)}
      {evidence.filter(item => item.tool === 'recurring_discovery').map((item, index) => <section className="assistant-evidence" key={`discovery:${index}`}>
        <h4>{en ? 'Possible monthly charges' : '可能的月付项目'}</h4>
        <p>{item.data.through.slice(0, 7)} · {item.data.candidate_count} {en ? 'candidates' : '组候选'} · {item.data.insufficient_count} {en ? 'insufficient' : '组证据不足'} · {item.data.ambiguous_count} {en ? 'ambiguous' : '组不明确'}</p>
        <p>{en ? 'Statement coverage is unverified.' : '账单覆盖尚未认证。'} · {item.data.rule_version}</p>
        <button onClick={() => onOpenDiscovery(item.data.target.through)}>{en ? 'Review evidence' : '查看发现证据'}</button>
      </section>)}
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
