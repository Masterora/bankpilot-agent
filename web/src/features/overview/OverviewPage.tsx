/**
 * 文件职责：提供基于真实账本关系汇总的财务总览。
 * 主要内容：共享期间、分币种收支指标、原始/调整对比图与核对入口。
 * 关键边界：金额来自服务端，不混算币种、不把净流入当余额；
 * 日期变更隔离读取状态，失败与空数据分别展示；总览不执行候选发现。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTimestamp } from '../../format'
import type { Messages, ProductPage } from '../../i18n'
import { LoadingIndicator, NavigationIcon, PageHeader } from '../../shared/ui'
import { PeriodFilter } from '../../shared/PeriodFilter'
import { validPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'
import { RelationReadiness } from './RelationReadiness'
import { NextActions } from './NextActions'
import type { ImportBatch, OverviewSnapshot, RelationWorkspace } from '../../types'

interface OverviewProps {
  english: boolean
  copy: Messages
  onNavigate: (page: ProductPage) => void
  planningRevision: number
  imports: ImportBatch[]
  importsLoading: boolean
  importsFailed: boolean
  onPlanning: (page: 'budgets' | 'recurring', month: string, target?: string) => void
  period: ReviewPeriod
  onPeriodChange: (period: ReviewPeriod) => void
}
export function OverviewPage(props: OverviewProps) {
  const { copy, english, period, onPeriodChange, onNavigate } = props
  return (
    <section className="product-page financial-overview">
      <div className="page-heading-actions">
        <PageHeader copy={copy} page="overview" />
        <button className="primary" onClick={() => onNavigate('import')}>
          <NavigationIcon kind="import" />
          {english ? 'Import statement' : '导入账单'}
        </button>
      </div>
      <PeriodFilter period={period} onChange={onPeriodChange} english={english} />
      {validPeriod(period) ? <OverviewData {...props} /> : null}
    </section>
  )
}

function OverviewData({
  english,
  period,
  onNavigate,
  imports,
  importsLoading,
  importsFailed,
  onPlanning,
  copy,
  planningRevision,
}: OverviewProps) {
  const [snapshot, setSnapshot] = useState<{
    data: OverviewSnapshot
    period: ReviewPeriod
    key: string
  } | null>(null)
  const [failedKey, setFailedKey] = useState<string | null>(null)
  const requestKey = `${period.start}:${period.end}`
  const failed = failedKey === requestKey
  const updating = snapshot?.key !== requestKey && !failed
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api
      .overview(period.start, period.end)
      .then((value) => {
        if (!active) return
        setSnapshot({
          data: value,
          period: { start: period.start, end: period.end },
          key: requestKey,
        })
        setFailedKey(null)
      })
      .catch(() => {
        if (active) setFailedKey(requestKey)
      })
    return () => {
      active = false
    }
  }, [period.start, period.end, requestKey, attempt])
  const failure = failed && (
    <div className="empty-state">
      <p role="alert">{english ? 'Unable to load overview' : '总览读取失败'}</p>
      <button
        onClick={() => {
          setFailedKey(null)
          setAttempt((value) => value + 1)
        }}
      >
        {english ? 'Retry' : '重试'}
      </button>
    </div>
  )
  if (!snapshot)
    return failure || <LoadingIndicator label={english ? 'Loading overview' : '正在读取总览'} />
  const data = snapshot.data
  const imported = imports.filter(
    (batch) => batch.status !== 'REVOKED' && batch.status !== 'REJECTED' && batch.imported_rows > 0,
  )
  const latestImport = imported
    .map((batch) => batch.created_at)
    .sort()
    .at(-1)
  const latestTransaction = data.recent_transactions
    .map((row) => row.booking_date)
    .sort()
    .at(-1)
  const locale = english ? 'en-US' : 'zh-CN'
  return (
    <div className="overview-data" aria-busy={updating}>
      {updating && <LoadingIndicator label={english ? 'Updating overview' : '正在更新总览'} />}
      {snapshot.key !== requestKey && (
        <p className="overview-retained-period">
          {english ? 'Displayed period' : '当前显示期间'}：{snapshot.period.start} —{' '}
          {snapshot.period.end}
        </p>
      )}
      {failure}
      <RelationReadiness
        key={`relations:${requestKey}`}
        start={period.start}
        end={period.end}
        english={english}
        onReview={() => onNavigate('relations')}
      />
      {!data.summaries.length && (
        <div className="ledger-welcome">
          <div className="welcome-symbol" aria-hidden="true">
            <NavigationIcon kind="review" />
          </div>
          <div>
            <h2>
              {imported.length
                ? english
                  ? 'No imported transactions in this period'
                  : '此期间没有已导入流水'
                : english
                  ? 'Your ledger starts here'
                  : '从第一份账单开始'}
            </h2>
            <p>
              {english
                ? 'Import a statement to see your income and spending.'
                : '导入账单，查看这段时间的收入与支出。'}
            </p>
            <button className="primary" onClick={() => onNavigate('import')}>
              {english ? 'Choose statement' : '选择账单'} <span aria-hidden="true">↗</span>
            </button>
          </div>
        </div>
      )}
      {data.summaries.map((summary) => (
        <section key={summary.currency} className="overview-currency" aria-label={summary.currency}>
          <div className="overview-money-row">
            <strong className="currency-stamp">{summary.currency}</strong>
            <Metric
              label={english ? 'Spending' : '支出'}
              value={formatMoney(summary.adjusted_outflow, summary.currency, locale)}
            />
            <Metric
              label={english ? 'Income' : '收入'}
              value={formatMoney(summary.adjusted_inflow, summary.currency, locale)}
            />
            <Metric
              label={english ? 'Net flow' : '收支净额'}
              value={formatMoney(summary.adjusted_net, summary.currency, locale)}
            />
          </div>
        </section>
      ))}
      <NextActions
        revision={planningRevision}
        key={`planning:${requestKey}`}
        month={period.end.slice(0, 7)}
        english={english}
        copy={copy}
        onPlanning={onPlanning}
      />
      <details className="data-coverage">
        <summary>{english ? 'Imported data scope' : '数据来源'}</summary>
        {importsFailed ? (
          <span>{english ? 'Import history unavailable' : '暂时无法读取导入范围'}</span>
        ) : importsLoading ? (
          <span>{english ? 'Loading data scope' : '正在读取数据范围'}</span>
        ) : (
          <>
            <span>
              {english ? 'Imported accounts' : '已导入账户'}：
              {[...new Set(imported.map((batch) => batch.account_name))].join('、') || '—'}
            </span>
            <span>
              {english ? 'Last import' : '最近导入'}：
              {latestImport ? formatTimestamp(latestImport, locale) : '—'}
            </span>
          </>
        )}
        <span>
          {english ? 'Latest entry in displayed period' : '当前显示期间最新交易'}：
          {latestTransaction ?? '—'}
        </span>
        <p>
            {english
              ? 'Dates reflect imported transactions. They do not prove that every account or day is complete.'
              : '日期来自已导入流水，不能证明所有账户或每一天的数据均完整。'}
        </p>
      </details>
      <details className="calculation-details">
        <summary>{english ? 'Calculation details by currency' : '计算口径'}</summary>
        {data.summaries.map((summary) => (
          <section key={summary.currency}>
            <h3>{summary.currency}</h3>
            <div className="overview-detail-grid">
              <article className="overview-panel">
                <h2>{english ? 'Raw and adjusted flows' : '原始与调整收支'}</h2>
                <FlowChart summary={summary} english={english} />
              </article>
              <article className="overview-panel">
                <h2>{english ? 'Calculation basis' : '计算口径'}</h2>
                <dl className="flow-breakdown">
                  <div>
                    <dt>{english ? 'Raw inflow' : '原始流入'}</dt>
                    <dd>{formatMoney(summary.raw_inflow, summary.currency, locale)}</dd>
                  </div>
                  <div>
                    <dt>{english ? 'Raw outflow' : '原始流出'}</dt>
                    <dd>{formatMoney(summary.raw_outflow, summary.currency, locale)}</dd>
                  </div>
                  <div>
                    <dt>{english ? 'Excluded duplicates' : '排除重复记录'}</dt>
                    <dd>{summary.duplicate_excluded}</dd>
                  </div>
                  <div>
                    <dt>{english ? 'Excluded transfer entries' : '排除转账流水'}</dt>
                    <dd>{summary.transfer_excluded}</dd>
                  </div>
                  <div>
                    <dt>{english ? 'Refund adjustment' : '退款冲减'}</dt>
                    <dd>{formatMoney(summary.refund_amount, summary.currency, locale)}</dd>
                  </div>
                </dl>
              </article>
            </div>
          </section>
        ))}
      </details>
      {data.recent_transactions.length > 0 && (
        <section className="recent-ledger">
          <header>
            <h2>{english ? 'Latest entries' : '最近流水'}</h2>
            <button onClick={() => onNavigate('review')}>
              {english ? 'View ledger' : '全部流水'} <span aria-hidden="true">↗</span>
            </button>
          </header>
          {data.recent_transactions.map((item) => (
            <div className="recent-entry" key={item.id}>
              <div>
                <strong>{item.merchant}</strong>
                <small>
                  {item.account_name} ·{' '}
                  {item.time_precision === 'date'
                    ? item.booking_date
                    : formatTimestamp(item.occurred_at, locale)}
                </small>
              </div>
              <span className="entry-amount">
                {formatMoney(item.amount, item.currency, locale)}
              </span>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="overview-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  )
}

/** 数值转换仅用于绘图比例；可读金额保持服务端 Decimal 字符串的精度。 */
function FlowChart({
  summary,
  english,
}: {
  summary: RelationWorkspace['summaries'][number]
  english: boolean
}) {
  const entries = [
    [english ? 'Raw inflow' : '原始流入', summary.raw_inflow, false],
    [english ? 'Adjusted inflow' : '收入', summary.adjusted_inflow, true],
    [english ? 'Raw outflow' : '原始流出', summary.raw_outflow, false],
    [english ? 'Adjusted outflow' : '调整后流出', summary.adjusted_outflow, true],
  ] as const
  const maximum = Math.max(...entries.map(([, value]) => Math.abs(Number(value))), 1)
  return (
    <div className="flow-chart">
      {entries.map(([label, value, adjusted]) => {
        const width = (Math.abs(Number(value)) / maximum) * 100
        return (
          <div className="flow-chart-row" key={label}>
            <div>
              <span>{label}</span>
              <strong>{formatMoney(value, summary.currency, english ? 'en-US' : 'zh-CN')}</strong>
            </div>
            <div className="flow-track">
              <i
                className={adjusted ? 'adjusted' : ''}
                style={{ width: `${Number.isFinite(width) ? width : 0}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
