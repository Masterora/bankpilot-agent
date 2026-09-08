/**
 * 文件职责：提供基于真实账本关系汇总的财务总览。
 * 主要内容：共享期间、分币种收支指标、原始/调整对比图与核对入口。
 * 关键边界：金额来自服务端，不混算币种、不把净流入当余额；
 * 日期变更隔离读取状态，失败与空数据分别展示，候选截断不宣称完整。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTimestamp } from '../../format'
import type { Messages, ProductPage } from '../../i18n'
import { NavigationIcon, PageHeader } from '../../shared/ui'
import { PeriodFilter } from '../../shared/PeriodFilter'
import { validPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'
import type { RelationWorkspace } from '../../types'

interface OverviewProps {
  english: boolean
  copy: Messages
  onNavigate: (page: ProductPage) => void
  period: ReviewPeriod
  onPeriodChange: (period: ReviewPeriod) => void
}
export function OverviewPage(props: OverviewProps) {
  const { copy, english, period, onPeriodChange, onNavigate } = props
  return <section className="product-page financial-overview">
    <div className="page-heading-actions"><PageHeader copy={copy} page="overview" /><button className="primary" onClick={() => onNavigate('import')}><NavigationIcon kind="import" />{english ? 'Import statement' : '导入账单'}</button></div>
    <PeriodFilter period={period} onChange={onPeriodChange} english={english} />
    {validPeriod(period)
      ? <OverviewData key={period.start + period.end} {...props} />
      : <p className="error" role="alert">{english ? 'Select a valid period of at most 366 days.' : '请选择有效期间，跨度不超过 366 天。'}</p>}
  </section>
}

function OverviewData({ english, period, onNavigate }: OverviewProps) {
  const [data, setData] = useState<RelationWorkspace | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api.relations(period.start, period.end)
      .then((value) => { if (active) setData(value) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [period.start, period.end, attempt])
  if (failed) return <div className="empty-state"><p role="alert">{english ? 'Unable to load overview' : '总览读取失败'}</p><button onClick={() => { setFailed(false); setAttempt((value) => value + 1) }}>{english ? 'Retry' : '重试'}</button></div>
  if (!data) return <div className="empty-state" role="status"><p>{english ? 'Loading ledger' : '正在读取账本'}</p></div>
  const pending = data.items.filter((item) => item.state === 'pending').length
  const locale = english ? 'en-US' : 'zh-CN'
  return <>
    {!data.summaries.length && <div className="ledger-welcome"><div className="welcome-symbol" aria-hidden="true"><NavigationIcon kind="review" /></div><div><h2>{english ? 'Your ledger starts here' : '从第一份账单开始'}</h2><p>{english ? 'Import a statement to see your income and spending.' : '导入账单，查看这段时间的收入与支出。'}</p><button className="primary" onClick={() => onNavigate('import')}>{english ? 'Choose statement' : '选择账单'} <span aria-hidden="true">↗</span></button></div></div>}
    {data.summaries.map((summary) => <section key={summary.currency} className="overview-currency" aria-label={summary.currency}>
      <div className="financial-summary">
        <article className="net-position">
          <div className="net-caption"><span>{english ? 'Adjusted net flow' : '本期净流入'}</span><span className="currency-stamp">{summary.currency}</span></div>
          <strong>{formatMoney(summary.adjusted_net, summary.currency, locale)}</strong>
          <div className="net-foot"><span>{english ? 'After confirmed adjustments' : '已确认关系调整后 · 非余额'}</span><span aria-hidden="true">↗</span></div>
        </article>
        <div className="income-expense">
        <Metric label={english ? 'Adjusted inflow' : '调整后流入'} value={formatMoney(summary.adjusted_inflow, summary.currency, locale)} note={english ? 'Confirmed relationships' : '已确认关系口径'} />
        <Metric label={english ? 'Adjusted outflow' : '调整后流出'} value={formatMoney(summary.adjusted_outflow, summary.currency, locale)} note={english ? 'Refunds by receipt date' : '退款按到账日冲减'} />
        </div>
      </div>
      <div className="overview-detail-grid">
        <article className="overview-panel"><h2>{english ? 'Raw and adjusted flows' : '原始与调整收支'}</h2><FlowChart summary={summary} english={english} /></article>
        <article className="overview-panel"><h2>{english ? 'Calculation basis' : '计算口径'}</h2><dl className="flow-breakdown">
          <div><dt>{english ? 'Raw inflow' : '原始流入'}</dt><dd>{formatMoney(summary.raw_inflow, summary.currency, locale)}</dd></div>
          <div><dt>{english ? 'Raw outflow' : '原始流出'}</dt><dd>{formatMoney(summary.raw_outflow, summary.currency, locale)}</dd></div>
          <div><dt>{english ? 'Excluded duplicates' : '排除重复记录'}</dt><dd>{summary.duplicate_excluded}</dd></div>
          <div><dt>{english ? 'Excluded transfer entries' : '排除转账流水'}</dt><dd>{summary.transfer_excluded}</dd></div>
          <div><dt>{english ? 'Refund adjustment' : '退款冲减'}</dt><dd>{formatMoney(summary.refund_amount, summary.currency, locale)}</dd></div>
        </dl></article>
      </div>
    </section>)}
    {data.transactions.some((item) => item.booking_date >= period.start && item.booking_date <= period.end) && <section className="recent-ledger">
      <header><h2>{english ? 'Latest entries' : '最近流水'}</h2><button onClick={() => onNavigate('review')}>{english ? 'View ledger' : '全部流水'} <span aria-hidden="true">↗</span></button></header>
      {data.transactions.filter((item) => item.booking_date >= period.start && item.booking_date <= period.end).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || String(a.id).localeCompare(String(b.id))).slice(0, 5).map((item) => <div className="recent-entry" key={item.id}>
        <span className="entry-initial" aria-hidden="true">{item.merchant.slice(0, 1)}</span><div><strong>{item.merchant}</strong><small>{item.account_name} · {item.time_precision === 'date' ? item.booking_date : formatTimestamp(item.occurred_at, locale)}</small></div><span className="entry-amount">{formatMoney(item.amount, item.currency, locale)}</span>
      </div>)}
    </section>}
    <section className="review-queue">
      <h2>{english ? 'To review' : '待核对'} <span>{pending}</span></h2>
      <button onClick={() => onNavigate('relations')}>{english ? 'View relationships' : '查看关系'} <span aria-hidden="true">→</span></button>
    </section>
    {data.truncated && <p className="scope-note" role="status">{english ? 'Candidate list is limited. Narrow the period to review more.' : '候选未全部列出，请缩短期间核对。'}</p>}
  </>
}
function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return <article className="overview-metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>
}

/** 数值转换仅用于绘图比例；可读金额保持服务端 Decimal 字符串的精度。 */
function FlowChart({ summary, english }: { summary: RelationWorkspace['summaries'][number]; english: boolean }) {
  const entries = [
    [english ? 'Raw inflow' : '原始流入', summary.raw_inflow, false],
    [english ? 'Adjusted inflow' : '调整后流入', summary.adjusted_inflow, true],
    [english ? 'Raw outflow' : '原始流出', summary.raw_outflow, false],
    [english ? 'Adjusted outflow' : '调整后流出', summary.adjusted_outflow, true],
  ] as const
  const maximum = Math.max(...entries.map(([, value]) => Math.abs(Number(value))), 1)
  return <div className="flow-chart">{entries.map(([label, value, adjusted]) => {
    const width = Math.abs(Number(value)) / maximum * 100
    return <div className="flow-chart-row" key={label}><div><span>{label}</span><strong>{formatMoney(value, summary.currency, english ? 'en-US' : 'zh-CN')}</strong></div><div className="flow-track"><i className={adjusted ? 'adjusted' : ''} style={{ width: `${Number.isFinite(width) ? width : 0}%` }} /></div></div>
  })}</div>
}
