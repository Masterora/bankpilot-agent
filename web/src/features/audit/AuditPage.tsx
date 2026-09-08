/**
 * 文件职责：展示 BankPilot 数据边界与当前 Agent 运行审计事件。
 *
 * 主要内容：自托管数据、模型、账户与密钥边界，以及按序号排列的运行事件。
 * 关键边界：页面只读取当前运行快照，不提供数据或权限修改入口。
 */

import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatTimestamp, formatTransactionTime } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { EmptyContent, PageHeader } from '../../shared/ui'
import type { Run } from '../../types'
import { ReviewSnapshot } from '../agent/ReviewSnapshot'

export function AuditPage({ copy, run, locale }: { copy: Messages; run: Run | null; locale: Locale }) {
  const [history, setHistory] = useState<{ id: string; message: string; status: string; created_at: string }[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const english = locale === 'en-US'
  useEffect(() => {
    let active = true
    api.runHistory().then((result) => { if (active) setHistory(result.items) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [attempt, run?.id, run?.status])
  useEffect(() => {
    if (!selectedId) return
    let active = true
    api.getRun(selectedId).then((result) => { if (active) setSelected(result) }).catch(() => { if (active) setFailed(true) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [selectedId, attempt])
  const displayed = selectedId ? selected : run
  const boundaries = [
    [copy.sourceDataBoundary, copy.sourceDataBoundaryDetail],
    [copy.modelBoundary, copy.modelBoundaryDetail],
    [copy.accountBoundary, copy.accountBoundaryDetail],
    [copy.secretBoundary, copy.secretBoundaryDetail],
  ]
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="audit" />
      <label>{english ? 'Recent runs · UTC+8' : '最近运行 · UTC+8'}<select value={selectedId} onChange={(event) => { setSelected(null); setFailed(false); setLoading(Boolean(event.target.value)); setSelectedId(event.target.value) }}><option value="">{english ? 'Current run' : '当前运行'}</option>{history.map((item) => <option key={item.id} value={item.id}>{formatTimestamp(item.created_at, english ? 'en-US' : 'zh-CN')} · {item.message} · {item.status}</option>)}</select></label>
      {loading && <p>{english ? 'Loading' : '正在读取'}</p>}
      {failed && <button onClick={() => { setFailed(false); setAttempt((a) => a + 1) }}>{english ? 'Request failed. Retry' : '读取失败，重试'}</button>}
      {displayed?.result && <details><summary>{english ? 'Result snapshot' : '结果快照'}</summary><p>{displayed.result.message}</p><p>{english ? 'Snapshot · Query again after changes' : '历史快照 · 更新后需重新查询'}</p><div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Time', 'Account', 'Merchant', 'Amount', 'Category'] : ['时间', '账户', '商户', '金额', '分类']).map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{displayed.result.transactions.items.map((item) => <tr key={item.id}><td className="time-cell">{formatTransactionTime(item, english ? 'en-US' : 'zh-CN')}</td><td>{item.account_name}</td><td>{item.merchant}</td><td>{item.amount} {item.currency}</td><td>{copy.categoryLabels[item.category]}</td></tr>)}</tbody></table></div></details>}
      {displayed?.result?.review && <ReviewSnapshot review={displayed.result.review} locale={english ? 'en-US' : 'zh-CN'} />}
      {displayed?.result && !displayed.result.review && <p className="scope-note">{english ? 'This result has no relationship review snapshot.' : '此结果未包含关系核查快照。'}</p>}
      <div className="audit-grid">
        <details className="audit-panel scope-note">
          <summary>{copy.auditBoundaryHeading}</summary>
          <div className="boundary-list">
            {boundaries.map(([title, detail]) => (
              <div className="boundary-item" key={title}>
                <span aria-hidden="true" />
                <div><strong>{title}</strong><p>{detail}</p></div>
              </div>
            ))}
          </div>
        </details>
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
          ) : <EmptyContent kind="audit" title={english ? 'No events to display' : '暂无可显示的事件'} detail={english ? 'Run a query or select a saved run to inspect its events.' : '发起核查或选择历史运行，查看对应事件。'}><a className="primary" href="#page=agent">{english ? 'Open review' : '前往核查'}</a></EmptyContent>}
        </article>
      </div>
    </section>
  )
}
