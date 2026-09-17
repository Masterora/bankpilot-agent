/**
 * 文件职责：提供独立的交易关系核对页面。
 * 主要内容：共享日期范围、输入校验与现有关系工作区装配。
 * 关键边界：沿用真实关系接口与版本校验，不在页面另建计算或模拟状态。
 */
import type { Messages } from '../../i18n'
import { PageHeader } from '../../shared/ui'
import { PeriodFilter } from '../../shared/PeriodFilter'
import { validPeriod } from '../../shared/period'
import type { ReviewPeriod } from '../../shared/period'
import { RelationsPanel } from './RelationsPanel'

export function RelationsPage({ copy, english, period, onPeriodChange, seedId, onImport }: {
  onImport: () => void; seedId?: string; copy: Messages; english: boolean; period: ReviewPeriod; onPeriodChange: (period: ReviewPeriod) => void
}) {
  return <section className="product-page">
    <PageHeader copy={copy} page="relations" />
    <PeriodFilter period={period} onChange={onPeriodChange} english={english} />
    {validPeriod(period)
      ? <RelationsPanel onImport={onImport} seedId={seedId} key={`${period.start}-${period.end}`} start={period.start} end={period.end} english={english} />
      : null}
  </section>
}
