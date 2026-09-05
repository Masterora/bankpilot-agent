/**
 * 文件职责：展示 Agent 任务输入、运行结果、账单核查和分类修正界面。
 *
 * 主要内容：任务输入、执行时间线、确定性统计、异常与交易证据。
 * 关键边界：页面不计算账务结果；金额、分类、异常和重算均来自受控 API。
 */

import { useRef } from 'react'
import type { FormEvent } from 'react'

import { formatMoney, formatTimestamp, formatTransactionTime } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { PageHeader } from '../../shared/ui'
import type { Run, TransactionCategory } from '../../types'

interface RunViewProps {
  copy: Messages
  correctingId: string | null
  locale: Locale
  onCategoryChange: (transactionId: string, category: TransactionCategory) => void
  run: Run | null
}

interface AgentPageProps extends RunViewProps {
  correctionSaved: boolean
  error: string
  message: string
  onMessageChange: (message: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  submitting: boolean
}

export function AgentPage({
  correctionSaved,
  copy,
  correctingId,
  error,
  locale,
  message,
  onCategoryChange,
  onMessageChange,
  onSubmit,
  run,
  submitting,
}: AgentPageProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="agent" />
      <section className="agent-command">
        <form aria-busy={submitting} className="prompt" onSubmit={onSubmit}>
          <textarea
            ref={inputRef}
            rows={3}
            aria-label={copy.queryInputLabel}
            aria-describedby="query-shortcut"
            value={message}
            onChange={(event) => onMessageChange(event.target.value)}
            maxLength={1000}
            onKeyDown={(event) => {
              // 多行输入保留 Enter 换行；快捷键只提交已完成的非空输入。
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !event.nativeEvent.isComposing && !submitting && message.trim()) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />
          <div className="prompt-footer">
          <span id="query-shortcut">{copy.queryShortcut}</span>
          <button
            aria-label={submitting ? copy.querying : copy.startQuery}
            className="primary"
            disabled={submitting || !message.trim()}
          >
            {submitting && <span className="button-spinner" aria-hidden="true" />}
            <span>{submitting ? copy.querying : copy.startQuery}</span>
          </button>
          </div>
        </form>
        <div className="suggestions">
          {copy.suggestions.map((item) => (
            <button type="button" key={item} onClick={() => { onMessageChange(item); inputRef.current?.focus() }}>{item}</button>
          ))}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {correctionSaved && <p role="status">{locale === 'en-US' ? 'Category saved to the ledger. Query again to generate an updated snapshot.' : '分类已保存到账本，请重新查询以生成新的结果快照。'}</p>}
      </section>
      <RunPanel
        copy={copy}
        correctingId={correctingId}
        locale={locale}
        onCategoryChange={onCategoryChange}
        run={run}
      />
    </section>
  )
}

function RunPanel({ copy, correctingId, locale, onCategoryChange, run }: RunViewProps) {
  if (!run) {
    return <section className="empty-state"><p>{copy.emptyResult}</p></section>
  }
  const transactions = run.result?.transactions.items ?? []
  const resultMessage = run.result
    ? copy.resultSummary(
        run.result.transactions.start_date,
        run.result.transactions.end_date,
        transactions.length,
      )
    : copy.statuses[run.status]
  return (
    <section className="results-grid" aria-live="polite">
      <article className="result-card">
        <div className="result-heading">
          <div><p className="eyebrow">{copy.resultEyebrow}</p><h2>{resultMessage}</h2></div>
          <Status copy={copy} status={run.status} />
        </div>
        {run.error_message && <p className="error">{run.error_code}: {run.error_message}</p>}
        {run.result && <AnalysisPanel copy={copy} locale={locale} run={run} />}
        {transactions.length > 0 && (
          <div className="transaction-list">
            {transactions.map((item) => (
              <div className="transaction" key={item.id}>
                <div className="merchant-mark">{item.merchant.slice(0, 1)}</div>
                <div className="transaction-copy">
                  <strong>{item.merchant}</strong>
                  <span>{formatTransactionTime(item, locale)}</span>
                  {item.description && <small>{item.description}</small>}
                  <select
                    aria-label={`${copy.categoryLabel}: ${item.merchant}`}
                    disabled={correctingId === item.id}
                    value={item.category}
                    onChange={(event) =>
                      onCategoryChange(item.id, event.target.value as TransactionCategory)
                    }
                  >
                    {Object.entries(copy.categoryLabels).map(([category, label]) => (
                      <option key={category} value={category}>{label}</option>
                    ))}
                  </select>
                </div>
                <strong className={Number(item.amount) >= 0 ? 'income' : ''}>
                  {formatMoney(item.amount, item.currency, locale)}
                </strong>
              </div>
            ))}
          </div>
        )}
      </article>
      <aside className="timeline-card">
        <p className="eyebrow">{copy.timelineEyebrow}</p>
        <ol>
          {run.events.map((event) => (
            <li key={event.sequence}><span /><div>{copy.events[event.event_type] ?? event.event_type}<small className="event-time">{formatTimestamp(event.occurred_at, locale)}</small></div></li>
          ))}
        </ol>
      </aside>
    </section>
  )
}

function AnalysisPanel({ copy, locale, run }: { copy: Messages; locale: Locale; run: Run }) {
  const analysis = run.result?.analysis
  if (!analysis) return null
  return (
    <div className="analysis-panel">
      <p className="eyebrow">{copy.analysisEyebrow}</p>
      <details className="scope-note"><summary>{locale === 'en-US' ? 'Data scope' : '统计口径'}</summary><p>{locale === 'en-US' ? 'Imported flows only. Transfers and refunds are not netted. Coverage is unverified; corrections require a new query.' : '仅统计导入流水，未抵销转账与退款，期间完整性未验证。修正后需重新查询。'}</p></details>
      <div className="summary-grid">
        {analysis.currency_summaries.map((summary) => (
          <div className="currency-summary" key={summary.currency}>
            <span>{summary.currency}</span>
            <dl>
              <div><dt>{copy.incomeLabel}</dt><dd className="income">{formatMoney(summary.income, summary.currency, locale)}</dd></div>
              <div><dt>{copy.expenseLabel}</dt><dd>{formatMoney(summary.expense, summary.currency, locale)}</dd></div>
              <div><dt>{copy.netLabel}</dt><dd>{formatMoney(summary.net, summary.currency, locale)}</dd></div>
            </dl>
          </div>
        ))}
      </div>
      <div className="analysis-columns">
        <section>
          <h3>{copy.categoryBreakdown}</h3>
          <div className="category-bars">
            {analysis.category_summaries.map((summary) => (
              <div className="category-row" key={`${summary.currency}-${summary.category}`}>
                <span>{copy.categoryLabels[summary.category]}</span>
                <i
                  style={{
                    width: `${categoryWidth(
                      summary.amount,
                      analysis.category_summaries
                        .filter((item) => item.currency === summary.currency)
                        .map((item) => item.amount),
                    )}%`,
                  }}
                />
                <strong>{formatMoney(summary.amount, summary.currency, locale)}</strong>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>{copy.anomalyHeading}</h3>
          {analysis.anomalies.length === 0 ? (
            <p className="muted">{copy.noAnomalies}</p>
          ) : (
            <ul className="anomaly-list">
              {analysis.anomalies.map((anomaly, index) => (
                <li className={`anomaly-${anomaly.severity}`} key={`${anomaly.rule_id}-${index}`}>
                  <span>!</span><p>{copy.anomalyDescription(anomaly)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

function categoryWidth(amount: string, amounts: string[]) {
  const maximum = Math.max(...amounts.map(Number), 1)
  return Math.max(5, Math.round((Number(amount) / maximum) * 100))
}

function Status({ copy, status }: { copy: Messages; status: Run['status'] }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>
      <i aria-hidden="true" />
      {copy.statuses[status]}
    </span>
  )
}
