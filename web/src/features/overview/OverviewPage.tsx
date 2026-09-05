/**
 * 文件职责：展示当前用户的财务总览与资金账户。
 *
 * 主要内容：最近运行指标、核心任务入口和实际资金账户。
 * 关键边界：页面只组合已加载数据，不自行读取 API 或推导账户余额。
 */

import type { Messages, ProductPage } from '../../i18n'
import { NavigationIcon, PageHeader } from '../../shared/ui'
import { Accounts } from './Accounts'
import type { Run } from '../../types'

export function OverviewPage({
  english,
  copy,
  onNavigate,
  run,
}: {
  english: boolean
  copy: Messages
  onNavigate: (page: ProductPage) => void
  run: Run | null
}) {
  const transactionCount = run?.result?.transactions.items.length ?? 0
  const signalCount = run?.result?.analysis.anomalies.length ?? 0
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="overview" />
      <section className="task-path" aria-label={copy.quickTasksHeading}>
        {(['import', 'agent', 'review'] as const).map((page, index) => (
          <button key={page} type="button" aria-label={page === 'agent' ? copy.openAgent : page === 'review' ? copy.openReview : copy.imports.chooseFile} onClick={() => onNavigate(page)}>
            <span className="task-path-top"><NavigationIcon kind={page} /><span>0{index + 1}</span></span>
            <strong>{copy.productPages[page].navigation}</strong>
            <span className="task-path-bottom">{copy.productPages[page].description}<span aria-hidden="true">↗</span></span>
          </button>
        ))}
      </section>
      <div className="overview-metrics">
        <Metric label={copy.transactionsMetric} value={run?.result ? String(transactionCount) : '—'} />
        <Metric label={copy.reviewSignalsMetric} value={run?.result ? String(signalCount) : '—'} />
        <Metric
          label={copy.latestRunMetric}
          value={run ? copy.statuses[run.status] : copy.noRunStatus}
        />
      </div>
      <Accounts english={english} />
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <article className="overview-metric"><span>{label}</span><strong>{value}</strong></article>
}
