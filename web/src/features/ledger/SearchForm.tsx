/**
 * 文件职责：提供账本与助手共用的手动搜索表单。
 * 主要内容：编辑日期、账户、币种、方向、金额、文本、分类及批次条件，显式提交搜索。
 * 关键边界：本地输入是草稿；不自行调用查询接口或将草稿写入地址。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Account } from '../../types'
import type { Messages } from '../../i18n'
import type { SearchFilters } from './search'
import { validPeriod } from '../../shared/period'

export function SearchForm({ initial, copy, english: en, busy, onSearch }: {
  initial: SearchFilters; copy: Messages; english: boolean; busy: boolean
  onSearch: (filters: SearchFilters) => void
}) {
  const [draft, setDraft] = useState(initial)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [error, setError] = useState('')
  useEffect(() => { let alive = true; api.listAccounts().then(data => { if (alive) setAccounts(data.items) }).catch(() => { if (alive) setError(en ? 'Accounts unavailable. Retry by reopening filters.' : '账户加载失败，请重新打开筛选。') }); return () => { alive = false } }, [en])
  const update = (patch: Partial<SearchFilters>) => setDraft(old => ({ ...old, ...patch }))
  return <form className="search-form" onSubmit={event => {
    event.preventDefault(); setError('')
    if (!validPeriod({ start: draft.start_date, end: draft.end_date })) { setError(en ? 'Choose an ordered period up to 366 days.' : '请选择不超过 366 天的有效日期范围。'); return }
    const min = draft.min_amount, max = draft.max_amount
    if ((min || max) && !draft.currency) { setError(en ? 'Select a currency for amount filters.' : '金额筛选必须选择币种。'); return }
    if (min && max && Number(min) > Number(max)) { setError(en ? 'Minimum must not exceed maximum.' : '最低金额不能大于最高金额。'); return }
    onSearch(draft)
  }}>
    <div className="ledger-filters">
      <label>{en ? 'From' : '开始日期'}<input required type="date" value={draft.start_date} onChange={e => update({ start_date: e.target.value })} /></label>
      <label>{en ? 'Through' : '结束日期'}<input required type="date" value={draft.end_date} onChange={e => update({ end_date: e.target.value })} /></label>
      <label>{en ? 'Merchant or note' : '商户或备注'}<input maxLength={100} value={draft.text ?? ''} onChange={e => update({ text: e.target.value })} /></label>
    </div>
    <details><summary>{en ? 'Filters' : '筛选'}</summary><div className="ledger-filters">
      <label>{en ? 'Account' : '账户'}<select value={draft.account_id ?? ''} onChange={e => update({ account_id: e.target.value || null })}><option value="">{en ? 'All accounts' : '全部账户'}</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}</select></label>
      <label>{en ? 'Currency' : '币种'}<input pattern="[A-Z]{3}" maxLength={3} value={draft.currency ?? ''} onChange={e => update({ currency: e.target.value.toUpperCase() || null })} /></label>
      <label>{en ? 'Direction' : '方向'}<select value={draft.direction ?? 'all'} onChange={e => update({ direction: e.target.value as SearchFilters['direction'] })}><option value="all">{en ? 'All' : '全部'}</option><option value="debit">{en ? 'Debit' : '支出'}</option><option value="credit">{en ? 'Credit' : '收入'}</option></select></label>
      <label>{en ? 'Minimum amount' : '最低金额'}<input inputMode="decimal" pattern="[0-9]{1,16}(\.[0-9]{1,2})?" value={draft.min_amount ?? ''} onChange={e => update({ min_amount: e.target.value || null })} /></label>
      <label>{en ? 'Maximum amount' : '最高金额'}<input inputMode="decimal" pattern="[0-9]{1,16}(\.[0-9]{1,2})?" value={draft.max_amount ?? ''} onChange={e => update({ max_amount: e.target.value || null })} /></label>
      <label>{en ? 'Text scope' : '文本范围'}<select value={draft.text_scope ?? 'merchant_or_note'} onChange={e => update({ text_scope: e.target.value as SearchFilters['text_scope'] })}><option value="merchant_or_note">{en ? 'Merchant or note' : '商户或备注'}</option><option value="merchant">{en ? 'Merchant only' : '仅商户'}</option></select></label>
      <label>{en ? 'Category' : '分类'}<select value={draft.category ?? ''} onChange={e => update({ category: (e.target.value || null) as SearchFilters['category'] })}><option value="">{en ? 'All categories' : '全部分类'}</option>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>{en ? 'Import batch' : '来源批次'}<input value={draft.import_batch_id ?? ''} onChange={e => update({ import_batch_id: e.target.value || null })} /></label>
    </div></details>
    {error && <p role="alert">{error}</p>}
    <button className="primary" disabled={busy}>{busy ? (en ? 'Searching…' : '查询中…') : (en ? 'Search' : '查询')}</button>
  </form>
}
