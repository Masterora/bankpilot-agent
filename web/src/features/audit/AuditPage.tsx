/**
 * 文件职责：展示 BankPilot 数据边界与当前 Agent 运行审计事件。
 *
 * 主要内容：自托管数据、模型、账户与密钥边界，以及按序号排列的运行事件。
 * 关键边界：页面只读取当前运行快照，不提供数据或权限修改入口。
 */

import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Messages } from '../../i18n'
import { PageHeader } from '../../shared/ui'
import type { Run } from '../../types'

export function AuditPage({ copy, run }: { copy: Messages; run: Run | null }) {
  const [history, setHistory] = useState<{ id: string; message: string; status: string; created_at: string }[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const english = document.documentElement.lang === 'en-US'
  useEffect(() => {
    let active = true
    api.runHistory().then((result) => { if (active) setHistory(result.items) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [attempt])
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
      <label>{english ? 'Recent runs (50)' : '最近运行（50 条）'}<select value={selectedId} onChange={(event) => { setSelected(null); setFailed(false); setLoading(Boolean(event.target.value)); setSelectedId(event.target.value) }}><option value="">{english ? 'Current run' : '当前运行'}</option>{history.map((item) => <option key={item.id} value={item.id}>{item.created_at.slice(0, 10)} · {item.message} · {item.status}</option>)}</select></label>
      {loading && <p>{english ? 'Loading' : '正在读取'}</p>}
      {failed && <button onClick={() => { setFailed(false); setAttempt((a) => a + 1) }}>{english ? 'Request failed. Retry' : '读取失败，重试'}</button>}
      {displayed?.result && <details><summary>{english ? 'Result snapshot' : '结果快照'}</summary><p>{displayed.result.message}</p><p>{english ? 'Historical data; query again after changes.' : '历史数据；账本变化后请重新查询。'}</p><div className="import-table-wrap"><table className="import-table"><tbody>{displayed.result.transactions.items.map((item) => <tr key={item.id}><td>{item.booking_date}</td><td>{item.account_name}</td><td>{item.merchant}</td><td>{item.amount} {item.currency}</td><td>{copy.categoryLabels[item.category]}</td></tr>)}</tbody></table></div></details>}
      <div className="audit-grid">
        <article className="audit-panel">
          <p className="eyebrow">{copy.auditBoundaryHeading}</p>
          <div className="boundary-list">
            {boundaries.map(([title, detail]) => (
              <div className="boundary-item" key={title}>
                <span aria-hidden="true" />
                <div><strong>{title}</strong><p>{detail}</p></div>
              </div>
            ))}
          </div>
        </article>
        <article className="audit-panel">
          <p className="eyebrow">{copy.auditEventsHeading}</p>
          {displayed?.events.length ? (
            <ol className="audit-events">
              {displayed.events.map((event) => (
                <li key={event.sequence}>
                  <span />{copy.events[event.event_type] ?? event.event_type}
                </li>
              ))}
            </ol>
          ) : <p className="module-empty-copy">{copy.productPages.audit.empty}</p>}
        </article>
      </div>
    </section>
  )
}
