import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { DetailPanel } from '../../shared/DetailPanel'
import type { NotificationItem, NotificationPage } from './types'
import type { AttentionType } from '../overview/attention'

const labels: Record<AttentionType, [string, string]> = {
  budget_near_limit: ['预算接近上限', 'Budget near limit'],
  budget_limit_reached: ['预算达到上限', 'Budget limit reached'],
  budget_overspent: ['预算已超支', 'Budget exceeded'],
  recurring_upcoming: ['固定支出即将到期', 'Payment due soon'],
  recurring_unreviewed: ['固定支出待核对', 'Payment needs review'],
  recurring_review_required: ['固定支出需重新核对', 'Payment needs another review'],
}

export function NotificationInbox({ userId, english, onNavigate, onQueryNavigate }: {
  userId: string
  english: boolean
  onNavigate: (item: NotificationItem) => void
  onQueryNavigate: (filters: import('../ledger/search').SearchFilters) => void
}) {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState<NotificationPage | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [seeing, setSeeing] = useState<string | null>(null)
  const identity = useRef(0)
  const dataVersion = useRef(0)
  const currentUser = useRef(userId)
  currentUser.current = userId
  const refreshRef = useRef<() => void>(() => {})

  useEffect(() => {
    const epoch = identity
    const requestIdentity = ++epoch.current
    let disposed = false
    let busy = false
    let available = false
    let dirty = false
    const valid = () => !disposed && identity.current === requestIdentity && currentUser.current === userId
    const refresh = async () => {
      if (!valid() || busy || document.visibilityState === 'hidden') return
      dirty = false
      busy = true
      const version = dataVersion.current
      const fresh = () => valid() && version === dataVersion.current
      try {
        const availability = await api.notificationAvailability()
        if (!fresh()) return
        available = availability.enabled
        setEnabled(available)
        if (!available) { setPage(null); setOpen(false); setError(false); return }
        const result = await api.notifications()
        if (fresh()) { setPage(result); setError(false) }
      } catch {
        if (fresh()) { setPage(null); setError(true) }
      } finally {
        busy = false
        if (dirty && valid()) void refresh()
      }
    }
    const changed = () => {
      dataVersion.current += 1
      dirty = true
      setPage(null)
      void refresh()
    }
    refreshRef.current = changed
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 60000)
    for (const event of ['focus', 'online', 'bankpilot:ledger-changed', 'bankpilot:planning-changed', 'bankpilot:attention-changed', 'bankpilot:query-subscription-changed']) window.addEventListener(event, changed)
    document.addEventListener('visibilitychange', changed)
    return () => {
      disposed = true
      epoch.current = requestIdentity + 1
      window.clearInterval(timer)
      for (const event of ['focus', 'online', 'bankpilot:ledger-changed', 'bankpilot:planning-changed', 'bankpilot:attention-changed', 'bankpilot:query-subscription-changed']) window.removeEventListener(event, changed)
      document.removeEventListener('visibilitychange', changed)
    }
  }, [userId])

  async function more() {
    if (!page?.next_cursor || loading) return
    const requestIdentity = identity.current
    const version = dataVersion.current
    const previous = page
    setLoading(true)
    try {
      const result = await api.notifications(previous.next_cursor ?? undefined)
      if (requestIdentity === identity.current && version === dataVersion.current && currentUser.current === userId) {
        setPage(current => current === previous ? { ...result, items: [...previous.items, ...result.items] } : current)
        setError(false)
      }
    } catch { if (requestIdentity === identity.current && version === dataVersion.current && currentUser.current === userId) setError(true) }
    finally { if (requestIdentity === identity.current) setLoading(false) }
  }

  async function visit(item: NotificationItem) {
    if (seeing) return
    const requestIdentity = identity.current
    setSeeing(item.id)
    let failed = false
    try { await api.notificationSeen(item.id) }
    catch { failed = true }
    if (requestIdentity !== identity.current || currentUser.current !== userId) return
    setSeeing(null)
    setError(failed)
    setOpen(false)
    onNavigate(item)
    if (!failed) refreshRef.current()
  }

  if (enabled === false) return null
  const title = english ? 'Notifications' : '站内通知'
  if (enabled === null) return <div className="notification-availability">
    <span role={error ? 'alert' : 'status'}>{error ? (english ? 'Notification status could not be loaded.' : '通知状态读取失败。') : (english ? 'Loading notifications…' : '正在读取通知状态…')}</span>
    {error && <button onClick={() => refreshRef.current()}>{english ? 'Retry notifications' : '重试读取通知'}</button>}
  </div>
  const status = page?.count_status === 'ready' && !error
    ? (english ? `${page.unseen_count} unseen` : `${page.unseen_count} 条未查看`)
    : (english ? 'Sync pending' : '待同步')
  return <>
    <button className="assistant-trigger" aria-expanded={open} onClick={() => { setOpen(true); refreshRef.current() }}>
      {title}<span role="status" aria-atomic="true">{status}</span>
    </button>
    {error && <span role="alert">{english ? 'Notifications could not be updated.' : '通知更新失败。'}</span>}
    <DetailPanel open={open} title={title} closeLabel={english ? 'Close' : '关闭'} onClose={() => setOpen(false)}>
      <div className="notification-inbox">
        <button onClick={() => refreshRef.current()}>{english ? 'Refresh' : '刷新'}</button>
        {!page && !error && <p role="status">{english ? 'Loading…' : '加载中…'}</p>}
        {page?.items.length === 0 && page.query_changes.length === 0 && <p>{english ? 'No notifications' : '暂无通知'}</p>}
        {page?.query_changes.map(item => <article key={`query:${item.conversation_id}`} className="notification-card">
          <h3>{english ? 'Saved query changed' : '已保存查询有变化'}</h3>
          <p>{item.title} · {item.filters.start_date} — {item.filters.end_date}</p>
          <button disabled={seeing !== null} onClick={() => {
            const requestIdentity = identity.current
            setSeeing(item.conversation_id)
            void api.assistantSubscriptionSeen(item.conversation_id, item.changed_at).then(() => {
              if (requestIdentity === identity.current && currentUser.current === userId) refreshRef.current()
            }).catch(() => { if (requestIdentity === identity.current) setError(true) }).finally(() => {
              if (requestIdentity !== identity.current || currentUser.current !== userId) return
              setSeeing(null); setOpen(false); onQueryNavigate(item.filters)
            })
          }}>{english ? 'Open query' : '打开查询'}</button>
        </article>)}
        {page?.items.map(item => <article key={item.id} className="notification-card">
          <h3>{labels[item.attention_type][english ? 1 : 0]}</h3>
          <p>{item.title} · {item.source_date}</p>
          <p>{item.seen_at ? (english ? 'Seen' : '已查看') : (english ? 'Unseen' : '未查看')}</p>
          <button disabled={seeing !== null} onClick={() => { void visit(item) }}>{seeing === item.id ? (english ? 'Opening…' : '正在打开…') : (english ? 'Open item' : '查看事项')}</button>
        </article>)}
        {page?.next_cursor && <button disabled={loading} onClick={() => { void more() }}>{loading ? (english ? 'Loading…' : '加载中…') : (english ? 'Load more' : '加载更多')}</button>}
      </div>
    </DetailPanel>
  </>
}
