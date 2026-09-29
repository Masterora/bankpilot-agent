/** Read-only discovery; evidence and classification always come from the server. */
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import { currentPeriod } from '../../shared/period'
import type { Locale } from '../../i18n'
import type { LedgerEntry } from '../ledger/LedgerPage'
import type { RecurringDiscoveryPage } from './types'

function previousMonth() {
  const [year, month] = currentPeriod().start.slice(0, 7).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 2, 1))
  return date.toISOString().slice(0, 7)
}

export function RecurringDiscovery({
  open, locale, onClose, onInspect,
}: {
  open: boolean
  locale: Locale
  onClose: () => void
  onInspect: (entry: LedgerEntry) => void
}) {
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => english ? en : zh
  const [month, setMonth] = useState(previousMonth)
  const [page, setPage] = useState<RecurringDiscoveryPage | null>(null)
  const [items, setItems] = useState<RecurringDiscoveryPage['items']>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const requestEpoch = useRef(0)
  function close() {
    requestEpoch.current += 1
    onClose()
  }
  function reload() {
    requestEpoch.current += 1
    setPage(null)
    setItems([])
    setAttempt((value) => value + 1)
  }
  function selectMonth(value: string) {
    requestEpoch.current += 1
    setPage(null)
    setItems([])
    setMonth(value)
  }
  useEffect(() => {
    if (!open) return
    const requestId = ++requestEpoch.current
    setLoading(true)
    setError('')
    setPage(null)
    setItems([])
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month) || month > previousMonth()) {
      setError(english ? 'Select a completed month.' : '请选择已结束的完整月份。')
      setLoading(false)
      return
    }
    api.recurringDiscovery(month).then((response) => {
      if (requestId !== requestEpoch.current) return
      setPage(response)
      setItems(response.items)
    }).catch((cause: unknown) => {
      if (requestId === requestEpoch.current) setError(cause instanceof ApiError && cause.code === 'discovery_capacity'
        ? english ? 'More than 10,000 transactions; discovery is unavailable.' : '流水超过 10,000 笔，无法完整发现。'
        : english ? 'Discovery is unavailable. Try again.' : '发现结果暂不可用，请重试。')
    }).finally(() => { if (requestId === requestEpoch.current) setLoading(false) })
    return () => { if (requestId === requestEpoch.current) requestEpoch.current += 1 }
  }, [open, month, attempt, english])

  async function more() {
    if (!page || loading) return
    const requestId = ++requestEpoch.current
    const expectedMonth = month
    const expectedOffset = items.length
    const expectedToken = page.discovery_snapshot_token
    setLoading(true)
    setError('')
    try {
      const next = await api.recurringDiscovery(expectedMonth, expectedOffset, expectedToken)
      if (requestId !== requestEpoch.current) return
      if (next.discovery_snapshot_token !== expectedToken || next.offset !== expectedOffset || next.through !== `${expectedMonth}-01`) {
        throw new Error('Discovery page no longer matches the requested snapshot')
      }
      setPage(next)
      setItems((before) => [...before, ...next.items])
    } catch {
      if (requestId === requestEpoch.current) setError(t('结果已变化或读取失败，请从第一页重新读取。', 'Results changed or loading failed. Start again from page one.'))
    } finally {
      if (requestId === requestEpoch.current) setLoading(false)
    }
  }

  const reason: Record<string, string> = english ? {
    three_recent_months: 'Three recent consecutive months',
    fewer_than_three_months: 'Fewer than three observed months',
    recent_months_not_consecutive: 'Recent months are not consecutive',
    last_charge_not_recent: 'No recent observed charge',
    all_observations_refunded: 'All observed charges have confirmed refunds',
    multiple_charges_in_month: 'Multiple charges in one month',
    charge_dates_vary: 'Charge dates vary',
    amounts_vary: 'Amounts vary',
    existing_plan_or_match: 'Already managed by a plan',
  } : {
    three_recent_months: '最近连续三个月有观测',
    fewer_than_three_months: '观测不足三个月',
    recent_months_not_consecutive: '最近月份不连续',
    last_charge_not_recent: '最近没有观测到扣款',
    all_observations_refunded: '观测扣款均有已确认退款',
    multiple_charges_in_month: '同月有多笔扣款',
    charge_dates_vary: '扣款日期波动较大',
    amounts_vary: '金额波动较大',
    existing_plan_or_match: '已有项目管理',
  }
  return <DetailPanel open={open} title={t('发现可能的月付项目', 'Find possible monthly charges')} closeLabel={t('关闭', 'Close')} onClose={close}>
    <div className="recurring-discovery">
      <label>{t('截止完整月份', 'Through completed month')}
        <input type="month" min="1900-01" max={previousMonth()} value={month} onChange={(event) => selectMonth(event.target.value)} />
      </label>
      <p className="planning-hint">{t('仅读取最近 12 个完整月的已导入流水。空月表示未观察到，账单覆盖尚未认证。候选不会自动建项。', 'Reads imported transactions from the last 12 completed months. An empty month means no observation; statement coverage is unverified. Candidates never create plans automatically.')}</p>
      {error && <p className="error" role="alert">{error} <button onClick={reload}>{t('重读', 'Reload')}</button></p>}
      {loading && <p role="status">{t('正在读取完整证据…', 'Reading complete evidence…')}</p>}
      {page && <p role="status">{t(`读取 ${page.transaction_count} 笔流水 · ${page.total} 组`, `${page.transaction_count} transactions · ${page.total} groups`)}</p>}
      {page && page.excluded_counts.refunded > 0 && <p>{t(`${page.excluded_counts.refunded} 笔有已确认退款，未参与识别。`, `${page.excluded_counts.refunded} charges with confirmed refunds were excluded.`)}</p>}
      {page && page.excluded_counts.relationship > 0 && <p>{t(`${page.excluded_counts.relationship} 笔已确认重复或转账，未参与识别。`, `${page.excluded_counts.relationship} confirmed duplicates or transfers were excluded.`)}</p>}
      {page && page.excluded_counts.merchant_unknown > 0 && <p>{t(`${page.excluded_counts.merchant_unknown} 笔商户无法识别，未参与识别。`, `${page.excluded_counts.merchant_unknown} charges without an identifiable merchant were excluded.`)}</p>}
      {page && page.unidentified_refund_count > 0 && <section>
        <h2>{t('商户无法识别的退款排除证据', 'Refund exclusions without an identifiable merchant')}</h2>
        {page.unidentified_refund_count > page.unidentified_refunds.length && <p>{t(`共 ${page.unidentified_refund_count} 笔，仅显示最近 12 笔`, `${page.unidentified_refund_count} charges; showing the latest 12`)}</p>}
        <ul>{page.unidentified_refunds.map((observation) => <li key={observation.transaction_id}>
          <button className="transaction-link" onClick={() => { close(); onInspect({ transactionId: observation.transaction_id, period: { start: observation.booking_date, end: observation.booking_date } }) }}>{observation.booking_date} · {observation.account_name} · {observation.merchant} · {formatMoney(observation.amount, observation.currency, locale)} · {t('已确认退款，未参与识别', 'Confirmed refund; excluded')}</button>
        </li>)}</ul>
      </section>}
      {page && !page.total && <p>{t('当前规则未发现候选；这不表示没有固定支出。', 'No groups found under the current rule. This does not mean there are no recurring charges.')}</p>}
      <div className="recurring-discovery-list">
        {items.map((group) => <article className="planning-card" key={group.key}>
          <header><h2>{group.observations.at(-1)?.merchant ?? group.excluded_refunds.at(-1)?.merchant ?? group.normalized_merchant}</h2><span className="planning-status">{{ candidate: t('可能月付', 'Possible monthly'), insufficient: t('证据不足', 'Insufficient'), ambiguous: t('不明确', 'Ambiguous'), existing: t('已有项目', 'Existing plan') }[group.status]}</span></header>
          <p>{group.account_name} · {group.currency} · {reason[group.reason] ?? group.reason}</p>
          <p>{t('规范化商户', 'Normalized merchant')}: {group.normalized_merchant}</p>
          <p>{t('有效观测月份', 'Valid observed months')}: {group.observed_months.length ? group.observed_months.map((value) => value.slice(0, 7)).join('、') : t('无', 'None')}</p>
          {group.amount_min !== null && group.amount_max !== null && <p>{t('金额范围', 'Amount range')}: {formatMoney(group.amount_min, group.currency, locale)} – {formatMoney(group.amount_max, group.currency, locale)}</p>}
          {group.observation_count > group.observations.length && <p>{t(`共 ${group.observation_count} 笔，仅显示最近 12 笔`, `${group.observation_count} observed charges; showing the latest 12`)}</p>}
          <ul>{group.observations.map((observation) => <li key={observation.transaction_id}>
            <button className="transaction-link" onClick={() => { close(); onInspect({ transactionId: observation.transaction_id, period: { start: observation.booking_date, end: observation.booking_date } }) }}>{observation.booking_date} · {observation.merchant} · {formatMoney(observation.amount, group.currency, locale)}</button>
          </li>)}</ul>
          {group.excluded_refund_count > 0 && <p>{t(`${group.excluded_refund_count} 笔有已确认退款，未参与识别`, `${group.excluded_refund_count} charges with confirmed refunds were excluded`)}</p>}
          {group.excluded_refund_count > group.excluded_refunds.length && <p>{t('仅显示最近 12 笔退款排除证据', 'Showing the latest 12 excluded charges')}</p>}
          <ul>{group.excluded_refunds.map((observation) => <li key={observation.transaction_id}>
            <button className="transaction-link" onClick={() => { close(); onInspect({ transactionId: observation.transaction_id, period: { start: observation.booking_date, end: observation.booking_date } }) }}>{observation.booking_date} · {observation.merchant} · {formatMoney(observation.amount, group.currency, locale)} · {t('已确认退款，未参与识别', 'Confirmed refund; excluded')}</button>
          </li>)}</ul>
        </article>)}
      </div>
      {page?.has_more && <button disabled={loading} onClick={() => void more()}>{t('加载更多', 'Load more')}</button>}
    </div>
  </DetailPanel>
}
