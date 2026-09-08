/**
 * 文件职责：提供交易关系核对、人工配对和调整统计工作区。
 * 主要内容：期间数据加载、候选筛选、双边来源证据、确认/拒绝/撤销、汇总导出。
 * 关键边界：金额只展示服务端 Decimal 字符串；写入携带版本，成功后重读全部结果。
 */
import { useEffect, useState } from 'react'
import { ApiError, api } from '../../api'
import { EmptyContent } from '../../shared/ui'
import { formatMoney, formatTimestamp, formatTransactionTime } from '../../format'
import type { RelationKind, RelationTransaction, RelationWorkspace, TransactionRelation } from '../../types'

const errors: Record<string, [string, string]> = {
  distinct_same_currency: ['请选择同币种的两笔不同交易。', 'Select two distinct transactions in the same currency.'],
  duplicate_mismatch: ['重复记录须来自不同批次、金额相同，日期相差不超过一天。', 'Duplicates require different batches, equal amounts and dates within one day.'],
  transfer_mismatch: ['转账须为不同账户的等额收支，日期相差不超过三天。', 'Transfers require equal opposite amounts, different accounts and dates within three days.'],
  refund_mismatch: ['退款须在原支出后九十天内，金额不超过原支出。', 'Refunds must follow the expense within 90 days and not exceed it.'],
  transaction_already_linked: ['交易已有关联，请先撤销原关联。', 'Transaction already linked. Revoke the existing relation first.'],
  refund_exceeds_purchase: ['累计退款超过原支出。', 'Total refunds exceed the original expense.'],
  stale_version: ['状态已变更，请刷新后重试。', 'State changed. Refresh and retry.'],
  evidence_unavailable: ['源交易已不可用，请刷新。', 'Source transactions are unavailable. Refresh the page.'],
  narrow_period: ['交易数量超过工作区上限，请缩短期间。', 'Too many transactions. Select a shorter period.'],
  revoke_first: ['请先撤销已确认的关联。', 'Revoke the confirmed relation first.'],
  not_confirmed: ['关联未处于已确认状态，请刷新。', 'Relation is not confirmed. Refresh the page.'],
}

function errorText(error: unknown, english: boolean) {
  return error instanceof ApiError && errors[error.message]
    ? errors[error.message][english ? 1 : 0]
    : english ? 'Request failed. Retry.' : '请求失败，请重试。'
}

function kindLabel(kind: RelationKind, english: boolean) {
  return ({ duplicate: ['重复记录', 'Duplicate'], transfer: ['本人转账', 'Own transfer'], refund: ['退款', 'Refund'] })[kind][english ? 1 : 0]
}

export function RelationsPanel({ start, end, english }: { start: string; end: string; english: boolean }) {
  const [data, setData] = useState<RelationWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<TransactionRelation['state']>('pending')
  const [page, setPage] = useState(0)
  const [notice, setNotice] = useState(false)
  useEffect(() => {
    let active = true
    api.relations(start, end).then((value) => { if (active) { setData(value); setLoading(false) } })
      .catch((reason) => { if (active) { setData(null); setError(errorText(reason, english)); setLoading(false) } })
    return () => { active = false }
  }, [start, end, attempt, english])

  function refresh() { setLoading(true); setError(''); setAttempt((a) => a + 1) }

  /** 写入后重新查询，确认成功但重读失败时不继续展示旧统计。 */
  async function decide(relation: Pick<TransactionRelation, 'kind' | 'first_id' | 'second_id' | 'version'>, state: 'confirmed' | 'rejected' | 'revoked') {
    setBusy(true); setError(''); setNotice(false)
    try {
      await api.saveRelation({ kind: relation.kind, first_id: relation.first_id, second_id: relation.second_id, state, expected_version: relation.version })
      setNotice(true)
      refresh()
    } catch (reason) { setError(errorText(reason, english)) }
    finally { setBusy(false) }
  }

  const rows = data?.items.filter((r) => r.state === filter) ?? []
  const safePage = Math.min(page, Math.max(0, Math.ceil(rows.length / 20) - 1))
  const evidence = new Map(data?.transactions.map((t) => [t.id, t]))
  function exportSummary() {
    if (!data) return
    const header = ['start_date', 'end_date', 'currency', 'raw_inflow', 'raw_outflow', 'adjusted_inflow', 'adjusted_outflow', 'adjusted_net', 'refund_amount', 'duplicate_excluded', 'transfer_excluded']
    const csv = [header.join(','), ...data.summaries.map((s) => [start, end, s.currency, s.raw_inflow, s.raw_outflow, s.adjusted_inflow, s.adjusted_outflow, s.adjusted_net, s.refund_amount, s.duplicate_excluded, s.transfer_excluded].join(','))].join('\r\n')
    const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = `bankpilot-summary-${start}-${end}.csv`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="relations-panel" aria-label={english ? 'Transaction relationships' : '交易关系'}>
    {error && <p role="alert" className="error">{error} <button disabled={busy} onClick={refresh}>{english ? 'Refresh' : '刷新'}</button></p>}
    {notice && <p role="status">{english ? 'Saved' : '已保存'}</p>}
    {loading ? <p>{english ? 'Loading' : '正在读取'}</p> : data && <div className="relation-workspace-grid"><aside className="relation-summary">
      <div className="relation-summary-head"><h2>{english ? 'Adjusted flows' : '调整后收支'}</h2><button onClick={exportSummary} disabled={!data.summaries.length || busy}>{english ? 'Export summary' : '导出汇总'}</button></div>
      {data.summaries.map((s) => <div key={s.currency}><p className="currency-caption">{s.currency}</p><dl className="flow-breakdown">{(english ? [['Raw inflow', s.raw_inflow], ['Raw outflow', s.raw_outflow], ['Adjusted inflow', s.adjusted_inflow], ['Adjusted outflow', s.adjusted_outflow], ['Adjusted net flow', s.adjusted_net]] : [['原始流入', s.raw_inflow], ['原始流出', s.raw_outflow], ['调整后流入', s.adjusted_inflow], ['调整后流出', s.adjusted_outflow], ['调整后净流入', s.adjusted_net]]).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{formatMoney(value, s.currency, english ? 'en-US' : 'zh-CN')}</dd></div>)}</dl></div>)}
      {!data.summaries.length && <p>{english ? 'No transactions in this period' : '当前期间暂无流水'}</p>}
      <details className="scope-note"><summary>{english ? 'Adjustments' : '调整明细'}</summary>
        {data.summaries.map((s) => <p key={s.currency}>{s.currency} · {english ? 'Raw' : '原始'} {s.raw_inflow} / {s.raw_outflow} · {english ? 'Duplicates' : '重复'} {s.duplicate_excluded} · {english ? 'Transfers' : '转账'} {s.transfer_excluded} · {english ? 'Refunds' : '退款'} {s.refund_amount}</p>)}
      </details>
      <p className="coverage-note">{english ? 'Only confirmed relationships adjust totals. Net flow is not a balance.' : '仅确认关系调整统计，净流入不代表余额。'}</p>
      </aside><div className="relation-main">
      <ManualRelation transactions={data.transactions} start={start} end={end} english={english} busy={busy} onConfirm={(kind, first_id, second_id) => {
        const saved = data.items.find((r) => r.kind === kind && ((r.first_id === first_id && r.second_id === second_id) || (kind === 'duplicate' && r.first_id === second_id && r.second_id === first_id)))
        void decide({ kind, first_id, second_id, version: saved?.version ?? 0 }, 'confirmed')
      }} />
      <div className="relation-tabs" role="group" aria-label={english ? 'Relation status' : '关联状态'}>{(['pending', 'confirmed', 'rejected', 'revoked'] as const).map((s) => <button key={s} aria-pressed={filter === s} onClick={() => { setFilter(s); setPage(0) }}>{({ pending: ['待确认', 'Pending'], confirmed: ['已确认', 'Confirmed'], rejected: ['已排除', 'Rejected'], revoked: ['已撤销', 'Revoked'] })[s][english ? 1 : 0]} · {data.items.filter((i) => i.state === s).length}</button>)}</div>
      {data.truncated && <p role="status">{english ? 'Candidate search limited. Narrow the period or link records manually.' : '候选搜索已达上限，可缩短期间或手动关联。'}</p>}
      {!rows.length && <EmptyContent kind="relations" title={english ? 'No matching relationships' : '暂无对应关系'} detail={english ? 'Relationships appear here when matching entries are available. You can also link entries manually.' : '匹配到交易后在这里核对，也可以手动关联已有流水。'} />}
      {rows.slice(safePage * 20, (safePage + 1) * 20).map((r) => <RelationCard key={`${r.kind}-${r.first_id}-${r.second_id}-${r.version}`} relation={r} first={evidence.get(r.first_id)!} second={evidence.get(r.second_id)!} busy={busy} english={english} onDecide={decide} />)}
      {rows.length > 20 && <div className="relation-tabs"><button disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>{english ? 'Previous' : '上一页'}</button><span>{safePage + 1} / {Math.ceil(rows.length / 20)}</span><button disabled={(safePage + 1) * 20 >= rows.length} onClick={() => setPage(safePage + 1)}>{english ? 'Next' : '下一页'}</button></div>}
    </div></div>}
  </section>
}

function Evidence({ transaction, english, label }: { transaction: RelationTransaction; english: boolean; label: string }) {
  return <article className="relation-evidence"><small>{label}</small><strong>{formatMoney(transaction.amount, transaction.currency, english ? 'en-US' : 'zh-CN')}</strong><span>{transaction.account_name} · {transaction.merchant}</span><time>{formatTransactionTime(transaction, english ? 'en-US' : 'zh-CN')}</time><details><summary>{english ? 'Source' : '来源'}</summary><p>{transaction.description || '—'}</p><p>{english ? 'Batch' : '批次'}：{transaction.import_batch_id ?? '—'}</p><p>{english ? 'Row' : '源行'}：{transaction.source_row_number ?? '—'}</p></details></article>
}

function RelationCard({ relation, first, second, busy, english, onDecide }: { relation: TransactionRelation; first: RelationTransaction; second: RelationTransaction; busy: boolean; english: boolean; onDecide: (r: TransactionRelation, state: 'confirmed' | 'rejected' | 'revoked') => Promise<void> }) {
  const [swap, setSwap] = useState(false)
  const labels = relation.kind === 'duplicate' ? (english ? ['Keep', 'Exclude'] : ['保留记录', '排除记录']) : relation.kind === 'transfer' ? (english ? ['Outgoing', 'Incoming'] : ['转出', '转入']) : (english ? ['Original expense', 'Refund received'] : ['原消费', '退款到账'])
  return <article className="relation-card"><header><h3>{kindLabel(relation.kind, english)}</h3>{relation.updated_at && <time>{formatTimestamp(relation.updated_at, english ? 'en-US' : 'zh-CN')}</time>}</header>
    <div className="relation-pair"><Evidence transaction={swap ? second : first} english={english} label={labels[0]} /><Evidence transaction={swap ? first : second} english={english} label={labels[1]} /></div>
    <div className="relation-actions">{relation.state === 'confirmed' ? <button disabled={busy} onClick={() => void onDecide(relation, 'revoked')}>{english ? 'Revoke relation' : '撤销关联'}</button> : <>
      {relation.kind === 'duplicate' && <button disabled={busy} onClick={() => setSwap(!swap)}>{english ? 'Swap retained record' : '切换保留记录'}</button>}
      <button disabled={busy} onClick={() => void onDecide({ ...relation, first_id: swap ? second.id : first.id, second_id: swap ? first.id : second.id }, 'confirmed')}>{english ? 'Confirm relation' : '确认关联'}</button>
      {relation.state !== 'rejected' && <button disabled={busy} onClick={() => void onDecide(relation, 'rejected')}>{english ? 'Reject' : '排除候选'}</button>}
    </>}</div>
  </article>
}

/** 用户可补充规则未命中的关联；使用已加载流水选择，服务端仍执行全部事实校验。 */
function ManualRelation({ transactions, start, end, english, busy, onConfirm }: { transactions: RelationTransaction[]; start: string; end: string; english: boolean; busy: boolean; onConfirm: (kind: RelationKind, first: string, second: string) => void }) {
  const [kind, setKind] = useState<RelationKind>('transfer')
  const [first, setFirst] = useState('')
  const [second, setSecond] = useState('')
  const [search, setSearch] = useState('')
  const matches = transactions.filter((t) => `${t.account_name} ${t.merchant} ${t.amount} ${t.booking_date}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const visibleIds = new Set(matches.slice(0, 200).map((t) => t.id))
  const options = transactions.filter((t) => t.id === first || t.id === second || visibleIds.has(t.id))
  const touchesPeriod = transactions.some((t) => (t.id === first || t.id === second) && t.booking_date >= start && t.booking_date <= end)
  return <details className="scope-note"><summary>{english ? 'Link transactions' : '手动关联'}</summary><form className="manual-relation" onSubmit={(event) => { event.preventDefault(); if (!busy && first && second && first !== second && touchesPeriod) onConfirm(kind, first, second) }}>
    <label>{english ? 'Find transactions (including 90 days before and after)' : '查找交易（含期间前后 90 天）'}<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={english ? 'Account, merchant, amount or date' : '账户、商户、金额或日期'} /></label>
    {matches.length > 200 && <p>{english ? 'Showing 200 matches. Refine your search.' : '显示前 200 条，请缩小搜索范围。'}</p>}
    <label>{english ? 'Type' : '关系类型'}<select value={kind} disabled={busy} onChange={(e) => setKind(e.target.value as RelationKind)}>{(['duplicate', 'transfer', 'refund'] as const).map((k) => <option key={k} value={k}>{kindLabel(k, english)}</option>)}</select></label>
    {([first, second] as const).map((value, index) => <label key={index}>{kind === 'duplicate' ? (english ? ['Keep', 'Exclude'] : ['保留记录', '排除记录'])[index] : (english ? ['Original outflow', 'Incoming record'] : ['原支出记录', '到账记录'])[index]}<select required value={value} disabled={busy} onChange={(e) => (index === 0 ? setFirst : setSecond)(e.target.value)}><option value="">{english ? 'Select a transaction' : '选择交易'}</option>{options.map((t) => <option key={t.id} value={t.id}>{formatTransactionTime(t, english ? 'en-US' : 'zh-CN')} · {t.account_name} · {t.merchant} · {t.amount} {t.currency} · #{t.source_row_number ?? t.id.slice(0, 8)}</option>)}</select></label>)}
    {first && second && !touchesPeriod && <p>{english ? 'At least one transaction must fall within the selected period.' : '至少一笔交易须在当前期间内。'}</p>}
    <button disabled={busy || !first || !second || first === second || !touchesPeriod}>{english ? 'Confirm relation' : '确认关联'}</button>
  </form></details>
}
