/** Persistent, server-authoritative budget and recurring attention handling. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { formatMoney } from '../../format'
import type { Messages } from '../../i18n'
import { LoadingIndicator } from '../../shared/ui'
import { useAttentionOperation } from './useAttentionOperation'
import { newIdempotencyKey } from '../../shared/operationKey'
import type { PendingAttention } from './attentionRecovery'
import type {
  AttentionGroup, AttentionItem, AttentionPreference, AttentionResponse, AttentionStateRequest, AttentionType,
} from './attention'

interface Props {
  userId: string
  revision: number
  month: string
  english: boolean
  copy: Messages
  onPlanning: (page: 'budgets' | 'recurring', month: string, target?: string) => void
}
type View = 'current' | 'read' | 'snoozed' | 'settings'

export function NextActions({ userId, month: initialMonth, english, copy, onPlanning, revision }: Props) {
  const [month, setMonth] = useState(initialMonth)
  const [data, setData] = useState<AttentionResponse | null>(null)
  const [groupLoading, setGroupLoading] = useState({ budgets: true, recurring: true })
  const [groupErrors, setGroupErrors] = useState({ budgets: '', recurring: '' })
  const loading = groupLoading.budgets || groupLoading.recurring
  const error = groupErrors.budgets || groupErrors.recurring
  const [preferences, setPreferences] = useState<AttentionPreference[] | null>(null)
  const [preferenceError, setPreferenceError] = useState('')
  const [view, setView] = useState<View>('current')
  const sequence = useRef({ budgets: 0, recurring: 0, preferences: 0 })
  const activeMonth = useRef(month)
  const mounted = useRef(true)
  const section = useRef<HTMLElement>(null)
  const operation = useAttentionOperation(userId, english)
  const pending = operation.locked
  const t = useCallback((zh: string, en: string) => (english ? en : zh), [english])

  const load = useCallback(async (group: 'all' | 'budgets' | 'recurring' = 'all') => {
    if (!mounted.current || activeMonth.current !== month) return
    const targets = group === 'all' ? ['budgets', 'recurring'] as const : [group]
    const requests = targets.map((target) => [target, ++sequence.current[target]] as const)
    const valid = () => mounted.current && activeMonth.current === month
    const currentTargets = () => requests.filter(([target, request]) => request === sequence.current[target])
    setGroupLoading(current => ({ ...current, ...Object.fromEntries(targets.map(target => [target, true])) }))
    try {
      const response = await api.attention(month, group)
      if (!valid() || response.month !== `${month}-01`) return
      const accepted = currentTargets()
      if (!accepted.length) return
      setGroupErrors(current => ({ ...current, ...Object.fromEntries(accepted.map(([target]) => [target, ''])) }))
      setData((current) => {
        const next = current?.month === response.month ? { ...current } : { ...response, budgets: null, recurring: null }
        next.server_time = response.server_time
        next.next_refresh_at = response.next_refresh_at
        for (const [target] of accepted) next[target] = response[target]
        return next
      })
    } catch (reason) {
      if (!valid() || !currentTargets().length) return
      const message = reason instanceof ApiError && reason.status === 503
        ? t('待办暂时无法读取，请稍后重试。', 'Attention items are unavailable. Try again later.')
        : t('待办读取失败，请重试。', 'Could not load attention items. Try again.')
      setGroupErrors(current => ({ ...current, ...Object.fromEntries(currentTargets().map(([target]) => [target, message])) }))
    } finally {
      if (valid() && currentTargets().length) setGroupLoading(current => ({ ...current, ...Object.fromEntries(currentTargets().map(([target]) => [target, false])) }))
    }
  }, [month, t])

  const loadPreferences = useCallback(async () => {
    const request = ++sequence.current.preferences
    try {
      const result = await api.attentionPreferences()
      if (!mounted.current || request !== sequence.current.preferences) return
      setPreferences(result)
      setPreferenceError('')
    } catch {
      if (mounted.current && request === sequence.current.preferences) {
        setPreferenceError(t('提醒设置读取失败，请重试。', 'Could not load settings. Try again.'))
      }
    }
  }, [t])
  useEffect(() => {
    mounted.current = true
    const logout = () => { mounted.current = false }
    window.addEventListener('bankpilot-logout', logout)
    const requests = sequence.current
    return () => {
      mounted.current = false
      window.removeEventListener('bankpilot-logout', logout)
      requests.budgets++
      requests.recurring++
      requests.preferences++
    }
  }, [])
  useEffect(() => { void load(); void loadPreferences() }, [load, loadPreferences, revision])
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === 'visible') { void load(); void loadPreferences() }
    }
    const timer = window.setInterval(refresh, 60_000)
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    window.addEventListener('online', refresh)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('online', refresh)
    }
  }, [load, loadPreferences])
  useEffect(() => {
    if (!data || data.month !== `${month}-01`) return
    const delay = Math.max(1_000, Date.parse(data.next_refresh_at) - Date.parse(data.server_time))
    if (delay > 60_000) return
    const timer = window.setTimeout(() => {
      if (document.visibilityState === 'visible') void load()
    }, delay)
    return () => window.clearTimeout(timer)
  }, [data, load, month])

  const submitOperation = async (request?: PendingAttention) => {
    if (!await operation.submit(request) || !mounted.current) return
    await load()
    await loadPreferences()
    window.requestAnimationFrame(() => {
      if (!mounted.current || activeMonth.current !== month) return
      const next = section.current?.querySelector<HTMLElement>('.attention-item button:not(:disabled)')
      ;(next ?? section.current?.querySelector<HTMLElement>('h2'))?.focus()
    })
  }

  const mutate = async (
    item: AttentionItem,
    action: AttentionStateRequest['action'],
    snooze_option?: AttentionStateRequest['snooze_option'],
  ) => {
    return submitOperation({ user_id: userId, kind: 'state', payload: {
      ...item.source,
      operation_id: newIdempotencyKey(), action,
      fact_token: item.fact_token,
      expected_state_version: item.state_version,
      ...(snooze_option ? { snooze_option } : {}),
    } })
  }

  const changePreference = async (type: AttentionType, enabled: boolean, version: number) => {
    if (operation.locked) return
    if (!enabled && !window.confirm(t(
      '关闭后只会隐藏这一类提醒，不会修改预算、流水或固定支出。继续吗？',
      'This only hides this reminder type. It does not change financial facts. Continue?',
    ))) return
    const payload = { operation_id: newIdempotencyKey(), enabled, expected_version: version }
    await submitOperation({ user_id: userId, kind: 'preference', type, payload })
  }

  const groups = [data?.budgets, data?.recurring]
    .filter((group): group is AttentionGroup => Boolean(group))
  const unread = groups.reduce((count, group) => count + group.unread.length, 0)
  const incomplete = loading || Boolean(error) || groups.length !== 2 || groups.some((group) => group.status !== 'ready')
  return <section className="next-actions" aria-label={t('需要关注', 'Needs attention')} ref={section}>
    <header>
      <h2 tabIndex={-1}>{t('本月关注', 'Monthly review')} <span className="attention-count">{incomplete ? t(`${unread}（未完整读取）`, `${unread} (incomplete)`) : unread}</span></h2>
      <label><span className="visually-hidden">{t('月度提醒月份', 'Monthly reminders')}</span>
        <input type="month" min="1900-01" max="9998-12" value={month} onChange={(event) => {
          if (/^\d{4}-\d{2}$/.test(event.target.value)) {
            activeMonth.current = event.target.value
            sequence.current.budgets++
            sequence.current.recurring++
            setData(null)
            setMonth(event.target.value)
          }
        }} />
      </label>
    </header>
    <nav className="attention-tabs" aria-label={t('待办视图', 'Attention views')}>
      {(['current', 'read', 'snoozed', 'settings'] as View[]).map((entry) => <button
        key={entry} aria-pressed={view === entry} onClick={() => setView(entry)}
      >{{ current: t('未读', 'Unread'), read: t('已读', 'Read'), snoozed: t('稍后处理', 'Snoozed'), settings: t('提醒设置', 'Settings') }[entry]}</button>)}
    </nav>
    {loading && !data && <LoadingIndicator label={t('正在读取待办', 'Loading attention items')} />}
    {error && <p className="error" role="alert">{error} <button onClick={() => void load()}>{t('重新读取', 'Reload')}</button></p>}
    {operation.error && <p className="error" role="alert">{operation.error} {operation.state.phase === 'unconfirmed'
      ? <button onClick={() => void submitOperation()}>{t('重试原操作', 'Retry original')}</button>
      : operation.state.phase === 'blocked'
      ? <button onClick={operation.recover}>{t('重试恢复', 'Retry recovery')}</button>
      : <button onClick={() => { operation.recover(); void load(); void loadPreferences() }}>{t('重新读取', 'Reload')}</button>}</p>}
    {view === 'settings' && preferenceError && <p className="error" role="alert">{preferenceError} <button onClick={() => void loadPreferences()}>{t('重试', 'Retry')}</button></p>}
    <div className="next-actions-grid">
      <AttentionColumn source="budget" preferences={preferences?.filter((item) => item.attention_type.startsWith('budget_'))} group={data?.budgets} stale={Boolean(groupErrors.budgets) || groupLoading.budgets} view={view} pending={pending} english={english} copy={copy} t={t} onPlanning={onPlanning} month={month} onMutate={mutate} onPreference={changePreference} onRetry={() => void load('budgets')} />
      <AttentionColumn source="recurring" preferences={preferences?.filter((item) => item.attention_type.startsWith('recurring_'))} group={data?.recurring} stale={Boolean(groupErrors.recurring) || groupLoading.recurring} view={view} pending={pending} english={english} copy={copy} t={t} onPlanning={onPlanning} month={month} onMutate={mutate} onPreference={changePreference} onRetry={() => void load('recurring')} />
    </div>
  </section>
}

interface ColumnProps {
  stale: boolean
  preferences: AttentionPreference[] | undefined
  source: 'budget' | 'recurring'; group: AttentionGroup | null | undefined; view: View
  pending: boolean; english: boolean; copy: Messages; month: string
  t: (zh: string, en: string) => string; onPlanning: Props['onPlanning']
  onMutate: (item: AttentionItem, action: AttentionStateRequest['action'], option?: AttentionStateRequest['snooze_option']) => Promise<void>
  onPreference: (type: AttentionType, enabled: boolean, version: number) => Promise<void>
  onRetry: () => void
}

function AttentionColumn(props: ColumnProps) {
  const { source, group, stale, preferences, view, pending, english, copy, month, t, onPlanning, onMutate, onPreference, onRetry } = props
  const heading = source === 'budget' ? t('预算提醒', 'Budget alerts') : t('固定支出', 'Fixed expenses')
  if (view === 'settings') return <article><h3>{heading}</h3><div className="attention-settings">
    {!preferences && <p>{t('设置尚未读取', 'Settings not loaded')}</p>}
    {preferences?.map((preference) => <label key={preference.attention_type}>
      <input type="checkbox" checked={preference.enabled}
        disabled={pending}
        onChange={() => void onPreference(preference.attention_type, !preference.enabled, preference.version)} />
      <span>{attentionLabel(preference.attention_type, t)}</span>
    </label>)}
  </div>{group?.status === 'ready' && group.disabled_count > 0 && <p>{t(`已隐藏 ${group.disabled_count} 项`, `${group.disabled_count} hidden`)}</p>}</article>
  if (!group) return <article><h3>{heading}</h3><p>{t('待办尚未读取', 'Items not loaded')}</p></article>
  if (stale || group.status === 'unavailable') return <article><h3>{heading}</h3><p role="alert">{t('这一组尚未完成最新读取，已有状态未被清除。', 'This group is not up to date. Saved state was preserved.')}</p><button onClick={onRetry}>{t('重试本组', 'Retry group')}</button></article>
  const items = view === 'read' ? group.read : view === 'snoozed' ? group.snoozed : group.unread
  return <article><h3>{heading}</h3>{items.map((item) => <AttentionRow
    key={itemKey(item)} item={item} view={view} busy={pending}
    source={source} month={month} english={english} copy={copy} t={t}
    onPlanning={onPlanning} onMutate={onMutate}
  />)}{!items.length && <p>{view === 'current' ? t('当前没有未读待办', 'No unread items') : view === 'read' ? t('没有已读项目', 'No read items') : t('没有稍后处理项目', 'No snoozed items')}</p>}
    <button className="text-action" onClick={() => onPlanning(source === 'budget' ? 'budgets' : 'recurring', month)}>{source === 'budget' ? t('全部预算', 'All budgets') : t('全部固定支出', 'All recurring')}</button>
  </article>
}

function AttentionRow({ item, view, busy, source, month, english, copy, t, onPlanning, onMutate }: {
  item: AttentionItem; view: View; busy: boolean; source: 'budget' | 'recurring'; month: string
  english: boolean; copy: Messages; t: ColumnProps['t']; onPlanning: Props['onPlanning']; onMutate: ColumnProps['onMutate']
}) {
  const title = item.category ? copy.categoryLabels[item.category as keyof typeof copy.categoryLabels] : item.title
  return <div className="attention-item">
    <button className="next-action" onClick={() => onPlanning(
      source === 'budget' ? 'budgets' : 'recurring', month,
      source === 'budget' ? `budget-${item.category}-${item.currency}` : `recurring-${item.source.source_id}`,
    )}>
      <strong>{title} · {attentionLabel(item.attention_type, t)}</strong>
      <span>{item.source.source_date} · {item.current_amount !== null ? `${formatMoney(item.current_amount, item.currency, english ? 'en-US' : 'zh-CN')} / ` : ''}{formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}</span>
      {item.snoozed_until && <small>{t('恢复时间', 'Returns')} {new Intl.DateTimeFormat(english ? 'en-US' : 'zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(new Date(item.snoozed_until))}</small>}
    </button>
    <div className="attention-actions">{view === 'current' ? <>
      <button disabled={busy} onClick={() => void onMutate(item, 'read')}>{t('已读', 'Read')}</button>
      <select disabled={busy} aria-label={t('稍后处理时间', 'Snooze duration')} defaultValue=""
        onChange={(event) => {
          const option = event.target.value as AttentionStateRequest['snooze_option']
          if (option) void onMutate(item, 'snooze', option)
          event.target.value = ''
        }}>
        <option value="" disabled>{t('稍后处理', 'Snooze')}</option>
        <option value="two_hours">{t('两小时后', 'In two hours')}</option>
        <option value="tomorrow_09">{t('明天 09:00', 'Tomorrow 09:00')}</option>
        <option value="seven_days_09">{t('七天后 09:00', 'In seven days at 09:00')}</option>
      </select>
    </> : <button disabled={busy} onClick={() => void onMutate(item, 'restore')}>{t('恢复未读', 'Restore unread')}</button>}</div>
  </div>
}

function attentionLabel(type: AttentionType, t: (zh: string, en: string) => string) {
  return ({
    budget_near_limit: t('接近额度', 'Near limit'),
    budget_limit_reached: t('额度已用完', 'Limit reached'),
    budget_overspent: t('已超预算', 'Over budget'),
    recurring_upcoming: t('即将到期', 'Upcoming'),
    recurring_unreviewed: t('待核对', 'Unreviewed'),
    recurring_review_required: t('关联需重核', 'Review link'),
  })[type]
}

function itemKey(item: AttentionItem) {
  return `${item.source.source_type}:${item.source.source_id}:${item.source.source_date}`
}
