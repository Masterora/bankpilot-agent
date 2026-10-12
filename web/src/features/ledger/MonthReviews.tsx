/** Account month declarations, loaded separately from the filtered search results. */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatMoney } from '../../format'
import { usePlanningMonth } from '../planning/usePlanningMonth'

export interface AccountMonthReview {
  account_id: string
  account_name: string
  month: string
  status: 'open' | 'reviewed' | 'closed' | 'stale'
  saved_status: 'open' | 'reviewed' | 'closed'
  version: number
  ledger_revision: number
  confirmed_at: string | null
  transaction_count: number
  first_transaction_date: string | null
  last_transaction_date: string | null
  totals: { currency: string; inflow: string; outflow: string }[]
  can_close: boolean
}

async function load(month: string) {
  return { month, items: await api.monthReviews(month) }
}

export function MonthReviews({ initialMonth, english, active }: { initialMonth: string; english: boolean; active: boolean }) {
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(initialMonth)
  const [revision, setRevision] = useState(0)
  const [confirmation, setConfirmation] = useState<{ item: AccountMonthReview; action: 'review' | 'close' | 'reopen' } | null>(null)
  const state = usePlanningMonth(load, month, english, active && open, revision)
  const t = (zh: string, en: string) => english ? en : zh
  const labels = { open: t('待核对', 'Open'), reviewed: t('已核对', 'Reviewed'), closed: t('已月结', 'Closed'), stale: t('需重新核对', 'Review required') }
  useEffect(() => {
    const changed = () => { setRevision(value => value + 1); setConfirmation(null) }
    window.addEventListener('bankpilot:ledger-changed', changed)
    window.addEventListener('focus', changed)
    return () => { window.removeEventListener('bankpilot:ledger-changed', changed); window.removeEventListener('focus', changed) }
  }, [])
  return <details className="month-reviews" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t('账期核对与月结', 'Account month review and close')}</summary>
    <div className="planning-actions">
      <label>{t('账期月份', 'Account month')}<input type="month" value={month} min="1900-01" max="9998-12" disabled={state.busy} onChange={event => { if (event.target.value) { setMonth(event.target.value); setConfirmation(null) } }} /></label>
      <button disabled={state.loading || state.busy} onClick={() => { setConfirmation(null); void state.refresh() }}>{t('刷新账期', 'Refresh month')}</button>
    </div>
    <p>{t('按账户和月份读取已导入流水，不受下方搜索筛选影响。请自行与原账单核对；月结不阻止补录。账本任何变化都会要求重新核对。', 'Read the imported account month independently of search filters. Compare with your original statement. Closing allows later imports; any ledger change requires a new review.')}</p>
    {state.error && <p className="error" role="alert">{state.error}</p>}
    {state.notice && <p role="status">{state.notice}</p>}
    {state.loading && <p role="status">{t('读取账期…', 'Loading account month…')}</p>}
    {!state.loading && !state.error && state.data?.items.length === 0 && <p>{t('请先导入账户账单。', 'Import an account statement first.')}</p>}
    {state.data?.items.map(item => <article className="month-review-card" key={item.account_id}>
      <h3>{item.account_name} · {labels[item.status]}</h3>
      <p>{item.transaction_count} {t('笔流水', 'transactions')} · {item.first_transaction_date ?? '—'} — {item.last_transaction_date ?? '—'}</p>
      {item.totals.map(total => <p key={total.currency}>{total.currency} · {t('原始入账', 'Raw inflow')} {formatMoney(total.inflow, total.currency, english ? 'en-US' : 'zh-CN')} · {t('原始出账', 'Raw outflow')} {formatMoney(total.outflow, total.currency, english ? 'en-US' : 'zh-CN')}</p>)}
      {item.confirmed_at && <p>{t('最近确认', 'Last confirmation')} · {new Intl.DateTimeFormat(english ? 'en-US' : 'zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(new Date(item.confirmed_at))} · UTC+8</p>}
      {item.status === 'stale' && <p>{t('此前的核对或月结基于旧账本，需按当前数据重新确认。', 'The previous declaration uses an older ledger. Review the current data again.')}</p>}
      <div className="planning-actions">
        {item.status !== 'closed' && <button disabled={state.busy || state.loading || !!state.error} onClick={() => setConfirmation({ item, action: 'review' })}>{t('确认已核对', 'Confirm reviewed')}</button>}
        {item.can_close && <button disabled={state.busy || state.loading || !!state.error} onClick={() => setConfirmation({ item, action: 'close' })}>{t('月结', 'Close month')}</button>}
        {item.saved_status !== 'open' && <button disabled={state.busy || state.loading || !!state.error} onClick={() => setConfirmation({ item, action: 'reopen' })}>{t('重新打开', 'Reopen')}</button>}
      </div>
      {confirmation?.item.account_id === item.account_id && <div className="planning-confirm">
        <p>{confirmation.action === 'review'
          ? t(`我已对照原账单核对 ${month} · ${item.account_name} 的 ${item.transaction_count} 笔已导入流水（无流水也需自行确认）。这不代表银行认证或完整性保证。`, `I compared the ${item.transaction_count} imported transactions for ${month} · ${item.account_name} with my statement, including an empty month if applicable. This is my declaration, not bank certification.`)
          : confirmation.action === 'close' ? t('确认将此已结束月份标记为已月结？后续账本变化会使确认失效。', 'Mark this completed month closed? Later ledger changes invalidate the declaration.')
          : t('撤回当前核对与月结标记，重新打开账期？', 'Withdraw the current declaration and reopen this month?')}</p>
        <button disabled={state.busy || state.loading || !!state.error} onClick={async () => { if (await state.perform(() => api.changeMonthReview(confirmation.item, confirmation.action))) setConfirmation(null) }}>{t('确认账期操作', 'Confirm month action')}</button>
        <button disabled={state.busy} onClick={() => setConfirmation(null)}>{t('取消', 'Cancel')}</button>
      </div>}
    </article>)}
  </details>
}
