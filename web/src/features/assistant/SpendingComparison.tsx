/**
 * 文件职责：展示服务端冻结的双月消费比较。
 * 关键边界：金额、方向和排序均来自确定性结果；界面只格式化，不重新计算财务事实。
 */
import { useRef } from 'react'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { SpendingComparison as Comparison } from './types'

export function SpendingComparison({ comparison, turnId, copy, locale, ledgerRevision, onEvidence, onRecompare }: {
  comparison: Comparison
  turnId: string
  copy: Messages
  locale: Locale
  ledgerRevision: number
  onEvidence: (turnId: string, side: 'baseline' | 'target', category: Comparison['categories'][number]['category']) => void
  onRecompare: () => void
}) {
  // Each immutable result has its own mount (keyed by turn and calculated_at).
  // Previously saved results are also revalidated by the evidence endpoint.
  const observedRevision = useRef(ledgerRevision)
  const stale = observedRevision.current !== ledgerRevision
  const en = locale === 'en-US'
  const money = (value: string) => formatMoney(value, comparison.scope.currency, locale)
  const sign = (value: string) => value.startsWith('-') ? -1 : /^0(?:\.0+)?$/.test(value) ? 0 : 1
  const magnitude = (value: string) => value.startsWith('-') ? value.slice(1) : value
  const delta = sign(comparison.net_delta)
  const direction = delta > 0 ? (en ? 'increased' : '增加') : delta < 0 ? (en ? 'decreased' : '减少') : (en ? 'unchanged' : '持平')
  const period = (value: Comparison['baseline']) => `${value.start_date}—${value.end_date}`
  const coverage = (value: Comparison['baseline']) => value.coverage.transaction_count === 0
    ? (en ? 'No imported transactions' : '尚无已导入流水')
    : `${value.coverage.transaction_count} ${en ? 'transactions' : '笔流水'} · ${value.coverage.earliest_transaction_date ?? '—'}—${value.coverage.latest_transaction_date ?? '—'}`
  return <section className="comparison-card" aria-label={en ? 'Spending comparison' : '消费比较'}>
    <header>
      <h3>{period(comparison.target)} {en ? 'vs' : '对比'} {period(comparison.baseline)} · {comparison.scope.currency}</h3>
      <p className="comparison-time">{en ? 'Calculated then' : '当时比较'} · <time dateTime={comparison.calculated_at}>{new Date(comparison.calculated_at).toLocaleString(locale)}</time></p>
    </header>
    {comparison.data_status === 'both_missing' ? <p className="comparison-warning" role="status">{en ? 'Neither period has imported transactions. No comparison conclusion is shown.' : '两个期间均无已导入流水，不显示“持平”结论。'}</p> : <>
      <p className="comparison-total"><span>{en ? 'Net spending' : '实际支出'} {direction}</span><strong>{money(magnitude(comparison.net_delta))}</strong></p>
      {comparison.data_status !== 'comparable' && <p className="comparison-warning" role="status">{comparison.data_status === 'baseline_missing'
        ? (en ? 'The baseline has no imported transactions; do not interpret this as real growth.' : '基准期尚无已导入流水，不能解释为真实增长。')
        : (en ? 'The target has no imported transactions; do not interpret this as real savings.' : '目标期尚无已导入流水，不能解释为真实节省。')}</p>}
      <dl className="comparison-periods">
        {[['baseline', comparison.baseline], ['target', comparison.target]].map(([key, value]) => {
          const row = value as Comparison['baseline']
          return <div key={key as string}>
            <dt>{period(row)}</dt>
            <dd>{en ? 'Purchases' : '消费'} {money(row.gross_spending)} · {en ? 'Refunds' : '退款'} {money(row.refund_offset)} · {en ? 'Net' : '实际'} {money(row.net_spending)}</dd>
            <dd>{coverage(row)} · {en ? 'Completeness unverified' : '完整性未认证'}</dd>
          </div>
        })}
      </dl>
      <div className="comparison-categories">
        {comparison.categories.map(row => {
          const rowDelta = sign(row.delta)
          const rowDirection = rowDelta > 0 ? (en ? 'Increase' : '增加') : rowDelta < 0 ? (en ? 'Decrease' : '减少') : (en ? 'Unchanged' : '持平')
          return <article key={row.category} className="comparison-category">
            <div><strong>{copy.categoryLabels[row.category]}</strong><span>{rowDirection} {money(magnitude(row.delta))}</span></div>
            <p>{en ? 'Baseline' : '基准期'} {money(row.baseline_net)} · {en ? 'Target' : '目标期'} {money(row.target_net)}</p>
            <div className="comparison-actions">
              <button disabled={stale} onClick={() => onEvidence(turnId, 'baseline', row.category)}>{en ? 'View baseline evidence' : '查看基准期构成'}</button>
              <button disabled={stale} onClick={() => onEvidence(turnId, 'target', row.category)}>{en ? 'View target evidence' : '查看目标期构成'}</button>
            </div>
          </article>
        })}
      </div>
    </>}
    {stale && <p className="comparison-warning" role="status">{en ? 'The ledger changed. Historical totals remain, but evidence is unavailable.' : '账本已变化，历史合计保留，但构成证据已失效。'}</p>}
    <button className="comparison-recompare" onClick={onRecompare}>{en ? 'Recompare as of today' : '按当前日期重新比较'}</button>
  </section>
}
