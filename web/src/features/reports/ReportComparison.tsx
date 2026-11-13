/** Compare any owned saved baseline against the currently viewed frozen report. */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { formatMoney, formatTimestamp } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { MonthlyReport, ReportComparisonResult, ReportDetail } from '../../types'
import { downloadFile } from '../../shared/download'
import { apiErrorMessage } from '../../shared/apiErrors'

const fields: Record<string, [string, string]> = {
  income: ['原始收入', 'Raw income'],
  expense: ['原始支出', 'Raw spending'],
  net: ['原始净流入', 'Raw net'],
  transaction_count: ['流水数', 'Transactions'],
  import_batch_count: ['导入批次数', 'Import batches'],
  raw_inflow: ['原始流入', 'Raw inflow'],
  raw_outflow: ['原始流出', 'Raw outflow'],
  adjusted_inflow: ['调整后流入', 'Adjusted inflow'],
  adjusted_outflow: ['调整后流出', 'Adjusted outflow'],
  adjusted_net: ['调整后净流入', 'Adjusted net'],
  duplicate_excluded: ['排除重复数', 'Duplicates excluded'],
  transfer_excluded: ['排除转账数', 'Transfers excluded'],
  refund_amount: ['确认退款额', 'Confirmed refunds'],
  amount: ['分类原始支出', 'Raw category spending'],
}
const sections: Record<string, [string, string]> = {
  raw: ['原始收支', 'Raw totals'],
  adjusted: ['调整口径', 'Adjusted totals'],
  category: ['原始分类', 'Raw categories'],
  coverage: ['导入覆盖', 'Import coverage'],
  transactions: ['流水变化', 'Transaction changes'],
  relations: ['关系变化', 'Relation changes'],
  evidence: ['关联证据变化', 'Evidence changes'],
  anomalies: ['规则提示变化', 'Anomaly changes'],
}

export function ReportComparison({
  current,
  locale,
  copy,
}: {
  current: ReportDetail
  locale: Locale
  copy: Messages
}) {
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const [items, setItems] = useState<MonthlyReport[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [baseline, setBaseline] = useState<MonthlyReport | null>(null)
  const [result, setResult] = useState<ReportComparisonResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [listError, setListError] = useState('')
  const [retry, setRetry] = useState(0)
  const [section, setSection] = useState('transactions')
  const [page, setPage] = useState(0)
  const generation = useRef(0)
  useEffect(() => {
    let alive = true
    setLoading(true)
    setListError('')
    api
      .comparableReports(offset)
      .then((rows) => {
        if (alive) {
          setItems(rows.items)
          setHasMore(rows.has_more)
        }
      })
      .catch((e) => {
        if (alive) setListError(apiErrorMessage(e, english))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [offset, retry, english])
  useEffect(
    () => () => {
      generation.current++
    },
    [],
  )
  const changes = result?.changes.filter((change) => change.section === section) ?? []
  async function compare() {
    if (!baseline || busy) return
    const token = ++generation.current
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const response = await api.compareReports(baseline.id, current.id)
      if (token === generation.current) {
        setResult(response)
        setPage(0)
      }
    } catch (e) {
      if (token === generation.current)
        setError(
          apiErrorMessage(e, english, {
            report_not_found: [
              '报告已删除或不可访问，请刷新版本列表。',
              'Report deleted or unavailable. Refresh versions.',
            ],
            report_not_ready: ['请选择两份已生成报告。', 'Select two completed reports.'],
            report_comparison_same: ['请选择不同的基准报告。', 'Choose a different baseline.'],
            report_comparison_capacity: [
              '快照超过比较容量上限，请缩小范围。',
              'Snapshot exceeds comparison capacity.',
            ],
          }),
        )
    } finally {
      if (token === generation.current) setBusy(false)
    }
  }
  const choiceLabel = (item: MonthlyReport) =>
    `${item.month.slice(0, 7)} · ${formatTimestamp(item.created_at, locale)} · ${item.id.slice(0, 8)}`
  return (
    <section className="report-comparison">
      <h3>{t('月报比较', 'Report comparison')}</h3>
      <p>
        {t(
          '按已保存的月报比较，不重算历史数据。',
          'Compares saved reports without recalculating historical data.',
        )}
      </p>
      <p>
        {t('当前报告', 'Current report')}：{choiceLabel(current)}
      </p>
      {listError && (
        <p role="alert">
          {listError}
          <button disabled={loading} onClick={() => setRetry((v) => v + 1)}>
            {t('重试读取版本', 'Retry versions')}
          </button>
        </p>
      )}
      <div className="report-toolbar">
        <label>
          {t('基准报告（可跨月）', 'Baseline (any month)')}
          <select
            disabled={loading || busy || !!listError}
            value={baseline?.id ?? ''}
            onChange={(e) => {
              setBaseline(
                e.target.value
                  ? (items.find((item) => item.id === e.target.value) ?? baseline)
                  : null,
              )
              setResult(null)
              setError('')
            }}
          >
            <option value="">{t('选择已生成报告', 'Choose a saved report')}</option>
            {baseline && !items.some((item) => item.id === baseline.id) && (
              <option value={baseline.id}>{choiceLabel(baseline)}</option>
            )}
            {items
              .filter((item) => item.id !== current.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {choiceLabel(item)}
                </option>
              ))}
          </select>
        </label>
        <button disabled={busy || !baseline} onClick={() => void compare()}>
          {busy ? t('正在比较…', 'Comparing…') : t('比较两个快照', 'Compare snapshots')}
        </button>
      </div>
      <div className="report-toolbar">
        <button
          disabled={!offset || loading || busy}
          onClick={() => setOffset((v) => Math.max(0, v - 20))}
        >
          {t('上一页版本', 'Previous versions')}
        </button>
        <span>
          {t('版本页', 'Version page')} {offset / 20 + 1}
        </span>
        <button
          disabled={!hasMore || loading || busy || !!listError}
          onClick={() => setOffset((v) => v + 20)}
        >
          {t('下一页版本', 'Next versions')}
        </button>
      </div>
      {loading && <p role="status">{t('正在读取报告版本…', 'Loading report versions…')}</p>}
      {error && <p role="alert">{error}</p>}
      {result && (
        <>
          {!result.same_month && (
            <p>
              {t(
                '跨月比较：流水新增／移除表示两个统计期间的集合差异，不代表删除或新导入。',
                'Across months, entries may appear in only one report. This does not indicate a new import or deletion.',
              )}
            </p>
          )}
          {!result.same_rules && (
            <p role="alert">
              {t(
                '规则版本不同，差额可能包含口径变化，不能直接归因为消费变化。',
                'Rules differ; deltas may reflect rule changes as well as spending changes.',
              )}
            </p>
          )}
          {(result.before.candidates_truncated || result.after.candidates_truncated) && (
            <p>
              {t(
                '至少一个快照的关系候选未穷尽，候选差异不能作为完整核对结论。',
                'At least one snapshot has truncated relation candidates; differences are not a complete reconciliation.',
              )}
            </p>
          )}
          <details>
            <summary>{t('快照来源与覆盖范围', 'Snapshot provenance & coverage')}</summary>
            <div className="comparison-facts">
              <pre>{JSON.stringify(result.before, null, 2)}</pre>
              <pre>{JSON.stringify(result.after, null, 2)}</pre>
            </div>
          </details>
          <p>
            {t(
              '未出现的币种／分类按该快照的零值比较；覆盖范围未认证，不表示实际收支完整。',
              'Absent currencies/categories use zero for that snapshot. Import coverage remains unverified.',
            )}
          </p>
          {['raw', 'adjusted', 'category', 'coverage'].map((group) => (
            <details key={group} open={group === 'adjusted'}>
              <summary>{sections[group][english ? 1 : 0]}</summary>
              <div className="comparison-metrics">
                {result.metrics
                  .filter((row) => row.section === group)
                  .map((row) => {
                    const count = row.field.endsWith('_count') || row.field.endsWith('_excluded')
                    const value = (amount: string) =>
                      !count && row.currency ? formatMoney(amount, row.currency, locale) : amount
                    const category = row.key.split(':')[1]
                    return (
                      <div className="comparison-row" key={`${row.key}:${row.field}`}>
                        <strong>
                          {row.currency ?? ''}{' '}
                          {category
                            ? copy.categoryLabels[category as keyof typeof copy.categoryLabels]
                            : ''}{' '}
                          · {fields[row.field]?.[english ? 1 : 0] ?? row.field}
                        </strong>
                        <span>
                          {value(row.before)} → {value(row.after)}
                        </span>
                        <span>
                          {t('差额', 'Delta')} {value(row.delta)}
                        </span>
                      </div>
                    )
                  })}
              </div>
            </details>
          ))}
          <div className="report-toolbar">
            <label>
              {t('证据变化', 'Evidence changes')}
              <select
                value={section}
                onChange={(e) => {
                  setSection(e.target.value)
                  setPage(0)
                }}
              >
                {['transactions', 'relations', 'evidence', 'anomalies'].map((group) => (
                  <option value={group} key={group}>
                    {sections[group][english ? 1 : 0]} ·{' '}
                    {result.changes.filter((c) => c.section === group).length}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() =>
                downloadFile(
                  JSON.stringify(result, null, 2),
                  `bankpilot-comparison-${result.before_id}-${result.after_id}.json`,
                  'application/json',
                )
              }
            >
              {t('导出完整比较 JSON', 'Export full comparison JSON')}
            </button>
          </div>
          {!changes.length && <p>{t('此类证据无变化', 'No changes in this evidence group')}</p>}
          {changes.slice(page * 20, page * 20 + 20).map((change) => (
            <details key={change.key}>
              <summary>
                {change.kind === 'added'
                  ? t('新增', 'Added')
                  : change.kind === 'removed'
                    ? t('移除', 'Removed')
                    : t('变化', 'Changed')}{' '}
                · {String((change.after ?? change.before)?.merchant ?? change.key)}
              </summary>
              <div className="comparison-facts">
                <div>
                  <strong>{t('基准', 'Baseline')}</strong>
                  <pre>{JSON.stringify(change.before, null, 2)}</pre>
                </div>
                <div>
                  <strong>{t('当前', 'Current')}</strong>
                  <pre>{JSON.stringify(change.after, null, 2)}</pre>
                </div>
              </div>
            </details>
          ))}
          {!!changes.length && (
            <div className="report-toolbar">
              <button disabled={!page} onClick={() => setPage((v) => v - 1)}>
                {t('上一页证据', 'Previous evidence')}
              </button>
              <span>
                {page + 1} / {Math.ceil(changes.length / 20)}
              </span>
              <button
                disabled={(page + 1) * 20 >= changes.length}
                onClick={() => setPage((v) => v + 1)}
              >
                {t('下一页证据', 'Next evidence')}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
