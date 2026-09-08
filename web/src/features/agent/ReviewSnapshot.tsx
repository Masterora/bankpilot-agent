/**
 * 文件职责：呈现 Agent 生成时的交易关系、调整统计与来源证据。
 * 主要内容：分币种原始/调整金额、覆盖边界、关系版本及跨期双方流水。
 * 关键边界：所有内容来自持久化快照；不重算金额，不将候选或空数据解释为事实。
 */

import { formatMoney, formatTimestamp, formatTransactionTime } from '../../format'
import type { Locale } from '../../i18n'
import type { BillReview } from '../../types'

export function ReviewSnapshot({ review, locale }: { review: BillReview; locale: Locale }) {
  const english = locale === 'en-US'
  const confirmed = review.relations.filter((item) => item.state === 'confirmed')
  const pending = review.relations.filter((item) => item.state === 'pending')
  const evidence = new Map(review.evidence.map((item) => [item.id, item]))
  const kinds = { duplicate: english ? 'Duplicate' : '重复', transfer: english ? 'Transfer' : '本人转账', refund: english ? 'Refund' : '退款' }

  return <section className="review-snapshot" aria-label={english ? 'Review snapshot' : '核查快照'}>
    <div className="result-heading"><h3>{english ? 'Confirmed adjustments' : '已确认调整'}</h3><small>{formatTimestamp(review.snapshot_at, locale)}</small></div>
    <p>{review.coverage.start_date} — {review.coverage.end_date}</p>
    <p className="scope-note">{english
      ? `${review.coverage.transaction_count} transactions · ${review.coverage.import_batch_count} import batches · Coverage unverified`
      : `${review.coverage.transaction_count} 笔流水 · ${review.coverage.import_batch_count} 个批次 · 账期完整性未验证`}</p>
    {review.adjusted_summaries.length ? <div className="summary-grid">{review.adjusted_summaries.map((summary) => <article className="currency-summary" key={summary.currency}>
      <span>{summary.currency}</span>
      <dl>
        <div><dt>{english ? 'Raw inflow' : '原始流入'}</dt><dd>{formatMoney(summary.raw_inflow, summary.currency, locale)}</dd></div>
        <div><dt>{english ? 'Raw outflow' : '原始流出'}</dt><dd>{formatMoney(summary.raw_outflow, summary.currency, locale)}</dd></div>
        <div><dt>{english ? 'Adjusted inflow' : '调整后流入'}</dt><dd>{formatMoney(summary.adjusted_inflow, summary.currency, locale)}</dd></div>
        <div><dt>{english ? 'Adjusted outflow' : '调整后流出'}</dt><dd>{formatMoney(summary.adjusted_outflow, summary.currency, locale)}</dd></div>
        <div><dt>{english ? 'Adjusted net flow' : '调整后净流入'}</dt><dd>{formatMoney(summary.adjusted_net, summary.currency, locale)}</dd></div>
      </dl>
    </article>)}</div> : <p>{english ? 'No imported transactions in this period.' : '所选期间没有已导入流水。'}</p>}
    <p>{english ? `${confirmed.length} confirmed relationships · ${pending.length} visible candidates` : `${confirmed.length} 项确认关系 · ${pending.length} 项可见候选`}</p>
    {review.candidates_truncated && <p role="status">{english ? 'Candidate list is incomplete. Review a narrower period in the ledger.' : '候选未全部列出，请在账本缩小期间核查。'}</p>}
    {review.relations.filter((relation) => relation.state === 'confirmed' || relation.state === 'pending').map((relation) => <details className="scope-note" key={`${relation.kind}:${relation.first_id}:${relation.second_id}`}>
      <summary>{kinds[relation.kind]} · {relation.state === 'confirmed' ? (english ? `Confirmed · v${relation.version}` : `已确认 · v${relation.version}`) : (english ? 'Pending' : '待核对')}</summary>
      {[relation.first_id, relation.second_id].map((id, index) => {
        const item = evidence.get(id)
        const roles = relation.kind === 'duplicate' ? (english ? ['Retained record', 'Excluded record'] : ['保留记录', '排除记录']) : relation.kind === 'transfer' ? (english ? ['Outgoing', 'Incoming'] : ['转出', '转入']) : (english ? ['Original expense', 'Refund received'] : ['原消费', '退款到账'])
        return item ? <div className="snapshot-evidence" key={id}>
          <small>{roles[index]}</small>
          <strong>{item.merchant} · {formatMoney(item.amount, item.currency, locale)}</strong>
          <span>{item.account_name} · {formatTransactionTime(item, locale)}</span>
          {item.description && <span>{item.description}</span>}
          <small>{english ? 'Import batch' : '来源批次'}: {item.import_batch_id ?? '—'} · {english ? 'Row' : '行'} {item.source_row_number ?? '—'}</small>
        </div> : <p key={id}>{english ? 'Evidence unavailable in this snapshot.' : '此快照未包含该笔证据。'}</p>
      })}
    </details>)}
    <details className="scope-note"><summary>{english ? 'Calculation basis' : '计算口径'}</summary><p>{english ? 'Only confirmed relationships change adjusted flows. Refunds reduce outflow on the receipt date. Currencies remain separate. Update the ledger and query again to create a new snapshot.' : '仅确认关系影响调整统计。退款按到账日冲减流出，各币种独立计算。修改账本后重新查询以生成新快照。'}</p><small>{english ? 'Rule' : '规则'}: {review.rule_version}</small></details>
  </section>
}
