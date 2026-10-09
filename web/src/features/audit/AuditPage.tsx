/**
 * 文件职责：展示 BankPilot 当前与历史 Agent 运行审计事件。
 *
 * 主要内容：历史结果快照与按序号排列的运行事件。
 * 关键边界：页面只读取当前运行快照，不提供数据或权限修改入口。
 */

import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatTimestamp, formatTransactionTime } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { EmptyContent, LoadingIndicator, PageHeader } from '../../shared/ui'
import type { Run } from '../../types'
import { ReviewSnapshot } from '../agent/ReviewSnapshot'

export function AuditPage({ copy, run, locale }: { copy: Messages; run: Run | null; locale: Locale }) {
  const [history, setHistory] = useState<{ id: string; message: string; status: string; created_at: string }[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [historyFailed, setHistoryFailed] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [detailFailed, setDetailFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [historyAttempt, setHistoryAttempt] = useState(0)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const english = locale === 'en-US'
  useEffect(() => {
    let active = true
    setHistoryLoading(true)
    setHistoryFailed(false)
    api.runHistory().then((result) => { if (active) setHistory(result.items) })
      .catch(() => { if (active) setHistoryFailed(true) })
      .finally(() => { if (active) setHistoryLoading(false) })
    return () => { active = false }
  }, [historyAttempt, run?.id, run?.status])
  useEffect(() => {
    if (!selectedId) return
    let active = true
    api.getRun(selectedId).then((result) => { if (active) setSelected(result) })
      .catch(() => { if (active) setDetailFailed(true) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [selectedId, detailAttempt])
  const displayed = selectedId ? selected : run
  function selectRun(id: string) {
    setSelected(null)
    setDetailFailed(false)
    setLoading(Boolean(id))
    setSelectedId(id)
  }
  return (
    <section className="product-page audit-page">
      <PageHeader copy={copy} page="audit" />
      {historyLoading && <LoadingIndicator label={english ? 'Loading run history' : '正在读取运行记录'} />}
      {historyFailed && <p className="error" role="alert">{english ? 'Run history could not be loaded.' : '运行记录读取失败。'} {' '}<button onClick={() => setHistoryAttempt(value => value + 1)}>{english ? 'Retry history' : '重试读取记录'}</button></p>}
      <label>{english ? 'Recent runs · UTC+8' : '最近运行 · UTC+8'}<select value={selectedId} onChange={(event) => selectRun(event.target.value)}><option value="">{english ? 'Current run' : '当前运行'}</option>{history.map((item) => <option key={item.id} value={item.id}>{formatTimestamp(item.created_at, english ? 'en-US' : 'zh-CN')} · {item.message} · {copy.statuses[item.status as Run['status']] ?? item.status}</option>)}</select></label>
      {!!history.length && <div className="import-table-wrap audit-history"><table className="import-table"><thead><tr><th>{english ? 'Time' : '运行时间'}</th><th>{english ? 'Task' : '核查任务'}</th><th>{english ? 'Status' : '状态'}</th><th>{english ? 'Details' : '详情'}</th></tr></thead><tbody>{history.map(item => <tr key={item.id} className={selectedId === item.id ? 'selected-row' : ''}><td className="time-cell">{formatTimestamp(item.created_at, locale)}</td><td>{item.message}</td><td><span className={`status status-${item.status.toLowerCase()}`}>{copy.statuses[item.status as Run['status']] ?? item.status}</span></td><td><button aria-pressed={selectedId === item.id} onClick={() => { if (selectedId !== item.id) selectRun(item.id) }}>{english ? 'View' : '查看'}</button></td></tr>)}</tbody></table></div>}
      {loading && <LoadingIndicator label={english ? 'Loading audit' : '正在读取审计'} />}
      {detailFailed && <p className="error" role="alert">{english ? 'Run details could not be loaded.' : '运行详情读取失败。'} {' '}<button onClick={() => { setDetailFailed(false); setLoading(true); setDetailAttempt(value => value + 1) }}>{english ? 'Retry details' : '重试读取详情'}</button></p>}
      {displayed?.result && <details><summary>{english ? 'Result snapshot' : '结果快照'}</summary><p>{displayed.result.message}</p><p>{english ? 'Snapshot · Query again after changes' : '历史快照 · 更新后需重新查询'}</p><div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Time', 'Account', 'Merchant', 'Amount', 'Category'] : ['时间', '账户', '商户', '金额', '分类']).map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{displayed.result.transactions.items.map((item) => <tr key={item.id}><td className="time-cell">{formatTransactionTime(item, english ? 'en-US' : 'zh-CN')}</td><td>{item.account_name}</td><td>{item.merchant}</td><td className="ledger-amount">{item.amount} {item.currency}</td><td>{copy.categoryLabels[item.category]}</td></tr>)}</tbody></table></div></details>}
      {displayed?.result?.review && <ReviewSnapshot review={displayed.result.review} locale={english ? 'en-US' : 'zh-CN'} />}
      {displayed?.result && !displayed.result.review && <p className="scope-note">{english ? 'This result has no relationship review snapshot.' : '此结果未包含关系核查快照。'}</p>}
        <article className="audit-panel">
          <p className="eyebrow">{copy.auditEventsHeading}</p>
          {displayed?.events.length ? (
            <ol className="audit-events">
              {displayed.events.map((event) => (
                <li key={event.sequence}>
                  <span /><div>{copy.events[event.event_type] ?? event.event_type}<small className="event-time">{formatTimestamp(event.occurred_at, english ? 'en-US' : 'zh-CN')}</small></div>
                </li>
              ))}
            </ol>
          ) : !loading && !detailFailed && (displayed || (!historyLoading && !historyFailed)) && (
            <EmptyContent kind="audit" title={displayed
              ? (english ? 'This run has no recorded events' : '此运行暂无已记录事件')
              : history.length
                ? (english ? 'Select a run to view its events' : '请选择运行记录查看事件')
                : (english ? 'No runs yet' : '暂无运行记录')}>
              {!displayed && !history.length && <a className="primary" href="#page=agent">{english ? 'Open review' : '前往核查'}</a>}
            </EmptyContent>
          )}
        </article>
    </section>
  )
}
