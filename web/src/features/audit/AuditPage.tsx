/**
 * 文件职责：展示 BankPilot 数据边界与当前 Agent 运行审计事件。
 *
 * 主要内容：自托管数据、模型、账户与密钥边界，以及按序号排列的运行事件。
 * 关键边界：页面只读取当前运行快照，不提供数据或权限修改入口。
 */

import type { Messages } from '../../i18n'
import { PageHeader } from '../../shared/ui'
import type { Run } from '../../types'

export function AuditPage({ copy, run }: { copy: Messages; run: Run | null }) {
  const boundaries = [
    [copy.sourceDataBoundary, copy.sourceDataBoundaryDetail],
    [copy.modelBoundary, copy.modelBoundaryDetail],
    [copy.accountBoundary, copy.accountBoundaryDetail],
    [copy.secretBoundary, copy.secretBoundaryDetail],
  ]
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="audit" />
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
          {run?.events.length ? (
            <ol className="audit-events">
              {run.events.map((event) => (
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
