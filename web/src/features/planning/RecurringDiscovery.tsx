/** User decisions are persisted by the server; uncertain writes retain their original request. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import { currentPeriod } from '../../shared/period'
import { newIdempotencyKey } from '../../shared/operationKey'
import type { Locale } from '../../i18n'
import type { LedgerEntry } from '../ledger/LedgerPage'
import type { DiscoveryDecisionPage, DiscoveryDecisionRequest, RecurringDiscoveryPage, RecurringItem } from './types'

function previousMonth() {
  const [year, month] = currentPeriod().start.slice(0, 7).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 2, 1))
  return date.toISOString().slice(0, 7)
}

export function RecurringDiscovery({
  open, locale, onClose, onInspect, userId, plans,
}: {
  open: boolean
  locale: Locale
  onClose: () => void
  onInspect: (entry: LedgerEntry) => void
  userId: string
  plans: RecurringItem[]
}) {
  const english = locale === 'en-US'
  const t = useCallback((zh: string, en: string) => english ? en : zh, [english])
  const [month, setMonth] = useState(previousMonth)
  const [page, setPage] = useState<RecurringDiscoveryPage | null>(null)
  const [items, setItems] = useState<RecurringDiscoveryPage['items']>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [view, setView] = useState<'current' | 'ignored' | 'linked'>('current')
  const [history, setHistory] = useState<DiscoveryDecisionPage | null>(null)
  const [historyItems, setHistoryItems] = useState<DiscoveryDecisionPage['items']>([])
  const [target, setTarget] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<DiscoveryDecisionRequest | null>(null)
  const [storageBlocked, setStorageBlocked] = useState(false)
  const [evidence, setEvidence] = useState<Record<string, string>>({})
  const recoveryKey = `recurring-discovery-operation:${userId}`
  const requestEpoch = useRef(0)
  useEffect(() => {
    if (!open) return
    try {
      const saved = sessionStorage.getItem(recoveryKey)
      const parsed = saved ? JSON.parse(saved) as DiscoveryDecisionRequest : null
      if (parsed && (!parsed.operation_id || !parsed.group_key || !parsed.action || !Number.isInteger(parsed.expected_version))) throw new Error('Invalid recovery record')
      setPending(parsed)
      setStorageBlocked(false)
    } catch {
      setStorageBlocked(true)
      setError(t('无法读取待恢复操作，请检查浏览器存储。', 'Cannot read the pending action. Check browser storage.'))
    }
  }, [open, recoveryKey, t])
  function close() {
    requestEpoch.current += 1
    onClose()
  }
  function reload() {
    requestEpoch.current += 1
    setPage(null)
    setItems([])
    setHistory(null)
    setHistoryItems([])
    setAttempt((value) => value + 1)
  }
  function selectMonth(value: string) {
    requestEpoch.current += 1
    setPage(null)
    setItems([])
    setMonth(value)
  }
  function selectView(value: 'current' | 'ignored' | 'linked') {
    requestEpoch.current += 1
    setView(value)
    setPage(null)
    setHistory(null)
    setItems([])
    setHistoryItems([])
  }
  useEffect(() => {
    if (!open) return
    const requestId = ++requestEpoch.current
    setLoading(true)
    setError('')
    setPage(null)
    setItems([])
    setHistory(null)
    setHistoryItems([])
    if (view !== 'current') {
      api.recurringDiscoveryDecisions(view).then((response) => {
        if (requestId !== requestEpoch.current) return
        setHistory(response)
        setHistoryItems(response.items)
      }).catch(() => {
        if (requestId === requestEpoch.current) setError(t('已保存决定读取失败，请重试。', 'Could not load saved decisions. Try again.'))
      }).finally(() => { if (requestId === requestEpoch.current) setLoading(false) })
      return () => { if (requestId === requestEpoch.current) requestEpoch.current += 1 }
    }
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
  }, [open, month, attempt, english, view, t])

  async function submit(payload: DiscoveryDecisionRequest) {
    if (pending || storageBlocked) return
    try {
      sessionStorage.setItem(recoveryKey, JSON.stringify(payload))
    } catch {
      setError(t('浏览器无法保存操作，请检查存储后重试。', 'Browser storage is unavailable. Check it before retrying.'))
      return
    }
    setPending(payload)
    await retry(payload)
  }

  async function retry(payload: DiscoveryDecisionRequest) {
    setLoading(true)
    setError('')
    try {
      await api.recurringDiscoveryDecision(payload)
      sessionStorage.removeItem(recoveryKey)
      setPending(null)
      reload()
    } catch (cause) {
      if (cause instanceof ApiError && (
        cause.status === 409 || cause.status === 422 || cause.code === 'discovery_not_found'
      )) {
        try { sessionStorage.removeItem(recoveryKey); setPending(null) }
        catch { setStorageBlocked(true) }
        setError(t('证据或决定已变化，请重读后操作。', 'Evidence or decision changed. Reload before acting.'))
      } else {
        setError(t('结果不明。请用原请求重试。', 'Result unknown. Retry the original request.'))
      }
    } finally { setLoading(false) }
  }

  function act(group: RecurringDiscoveryPage['items'][number], action: 'ignore' | 'link') {
    if (!page) return
    const target_plan_id = action === 'link' ? target[group.key] : undefined
    if (action === 'link' && !target_plan_id) return
    void submit({
      operation_id: newIdempotencyKey(), group_key: group.key, action,
      expected_version: group.decision_version, through: page.through,
      evidence_digest: group.evidence_digest,
      discovery_snapshot_token: page.discovery_snapshot_token,
      ...(target_plan_id ? { target_plan_id } : {}),
    })
  }

  function undo(row: DiscoveryDecisionPage['items'][number]) {
    void submit({ operation_id: newIdempotencyKey(), group_key: row.group_key,
      action: row.status === 'ignored' ? 'restore' : 'unlink', expected_version: row.version })
  }

  async function more() {
    if (view !== 'current') {
      if (!history || loading) return
      const requestId = ++requestEpoch.current
      setLoading(true)
      try {
        const next = await api.recurringDiscoveryDecisions(view, historyItems.length, history.decision_snapshot_token)
        if (requestId !== requestEpoch.current) return
        setHistory(next)
        setHistoryItems((before) => [...before, ...next.items])
      } catch { if (requestId === requestEpoch.current) setError(t('列表已变化，请从第一页重读。', 'List changed. Reload from the first page.')) }
      finally { if (requestId === requestEpoch.current) setLoading(false) }
      return
    }
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
      <nav aria-label={t('发现视图', 'Discovery views')}>
        {(['current', 'ignored', 'linked'] as const).map((item) => <button key={item} aria-current={view === item ? 'page' : undefined} onClick={() => selectView(item)}>{item === 'current' ? t('当前发现', 'Current') : item === 'ignored' ? t('已忽略', 'Ignored') : t('已关联', 'Linked')}</button>)}
      </nav>
      <label>{t('截止完整月份', 'Through completed month')}
        <input type="month" min="1900-01" max={previousMonth()} value={month} onChange={(event) => selectMonth(event.target.value)} />
      </label>
      {storageBlocked && <p role="alert">{t('浏览器存储不可用，当前不能提交发现决定。', 'Browser storage is unavailable. Discovery actions are disabled.')}</p>}
      {pending && <p role="alert">{t('有结果不明的操作。', 'An action has an unknown result.')} <button disabled={loading || storageBlocked} onClick={() => void retry(pending)}>{t('按原请求重试', 'Retry original request')}</button></p>}
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
      {history && !history.total && <p>{t('没有已保存的决定。', 'No saved decisions.')}</p>}
      {historyItems.map((row) => <article className="planning-card" key={row.group_key}>
        <h2>{row.normalized_merchant}</h2>
        <p>{row.currency} · {row.status === 'ignored' ? t('已忽略', 'Ignored') : t('已关联', 'Linked')} · {row.needs_review ? t('需重新核对', 'Needs review') : !evidence[row.group_key] ? t('证据未核对', 'Evidence not checked') : ''}</p>
        {row.target_plan_id && <p>{t('目标项目', 'Plan')}: {plans.find((plan) => plan.id === row.target_plan_id)?.name ?? row.target_plan_id}</p>}
        <button disabled={loading || !!pending || storageBlocked} onClick={() => undo(row)}>{row.status === 'ignored' ? t('恢复', 'Restore') : t('解除关联', 'Unlink')}</button>
        <button disabled={loading} onClick={() => void api.recurringDiscoveryEvidence(row.group_key, month).then((result) => setEvidence((before) => ({ ...before, [row.group_key]: result.evidence_status }))).catch(() => setError(t('证据核对失败。', 'Evidence check failed.')))}>{t('核对当前证据', 'Check evidence')}</button>
        {evidence[row.group_key] && <p>{evidence[row.group_key] === 'present' ? t('当前窗口有证据', 'Evidence present in this window') : t('当前窗口无证据', 'No evidence in this window')}</p>}
      </article>)}
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
          {group.observation_count > 0 && <div>
            <button disabled={loading || !!pending || storageBlocked} onClick={() => act(group, 'ignore')}>{t('忽略', 'Ignore')}</button>
            <label>{t('关联已有项目', 'Link existing plan')}
              <select value={target[group.key] ?? ''} onChange={(event) => setTarget((before) => ({ ...before, [group.key]: event.target.value }))}>
                <option value="">{t('选择项目', 'Select plan')}</option>
                {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name} · {plan.currency}</option>)}
              </select>
            </label>
            <button disabled={loading || !!pending || storageBlocked || !target[group.key]} onClick={() => act(group, 'link')}>{t('确认关联', 'Confirm link')}</button>
          </div>}
        </article>)}
      </div>
      {(page?.has_more || history?.has_more) && <button disabled={loading} onClick={() => void more()}>{t('加载更多', 'Load more')}</button>}
    </div>
  </DetailPanel>
}
