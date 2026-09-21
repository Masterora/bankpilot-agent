/**
 * 文件职责：展示助手交易搜索结果及手动调整。
 * 主要内容：条件标签、带版本分页、交易详情、账本跳转、手动搜索和会话条件保存重试。
 * 关键边界：保留原查询结果；手动条件保存失败明确提示，迟到响应和账本变更不得继续使用旧证据。
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { Messages } from '../../i18n'
import { formatMoney } from '../../format'
import { SearchForm } from '../ledger/SearchForm'
import { searchError, versions, searchChips } from '../ledger/search'
import type { SearchFilters, SearchPage } from '../ledger/search'
import type { EvidenceTarget } from './types'

export function SearchResultCard({ initial, filters, english: en, copy, onInspect, onLedger, onSave, onUnsaved }: {
  initial?: SearchPage; filters?: SearchFilters; english: boolean; copy: Messages
  onInspect: (target: EvidenceTarget) => void; onLedger: (filters: SearchFilters) => void
  onSave: (filters: SearchFilters) => Promise<void>; onUnsaved: () => void
}) {
  const [result, setResult] = useState(initial)
  const [manual, setManual] = useState(false)
  const [editing, setEditing] = useState(!initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [unsaved, setUnsaved] = useState(false)
  const [stale, setStale] = useState(false)
  const epoch = useRef(0)
  useEffect(() => {
    const invalidate = () => { epoch.current++; setStale(true); setBusy(false) }
    window.addEventListener('bankpilot:ledger-changed', invalidate)
    return () => { invalidate(); window.removeEventListener('bankpilot:ledger-changed', invalidate) }
  }, [])
  const current = result?.filters ?? filters!
  async function save(value: SearchFilters) {
    try { await onSave(value); setUnsaved(false) }
    catch (cause) { setError(searchError(cause, en)); setUnsaved(true) }
  }
  async function query(value: SearchFilters, offset = 0, version?: SearchPage) {
    const id = ++epoch.current
    setBusy(true); setError('')
    try {
      const data = await api.search(value, offset, version ? versions(version) : undefined)
      if (epoch.current !== id) return
      setResult(data); setStale(false); setEditing(false)
      if (!version) { setManual(true); setUnsaved(true); onUnsaved(); await save(data.filters) }
    } catch (cause) { if (epoch.current === id) { setError(searchError(cause, en)); setStale(true) } }
    finally { if (epoch.current === id) setBusy(false) }
  }
  return <section className="assistant-search-result">
    {manual && initial && <section>
      <p>{en ? 'Original result' : '原查询结果'} · {initial.filters.start_date} — {initial.filters.end_date} · {initial.filters.text}</p>
      <strong>{en ? `${initial.total_count} transactions` : `共 ${initial.total_count} 笔`}</strong>
      <ul>{initial.items.map(row => <li key={row.id}><button disabled={busy} onClick={() => onInspect({ id: row.id, booking_date: row.booking_date, version: versions(initial) })}>{row.booking_date} · {row.merchant} · {formatMoney(row.amount, row.currency, en ? 'en-US' : 'zh-CN')}</button></li>)}</ul>
      <hr /><h4>{en ? 'Manual search' : '本次手动查询'}</h4>
    </section>}
    <p>{current.start_date} — {current.end_date}</p>
    <p>{searchChips(current, copy.categoryLabels, en).map(chip => chip.label).join(' · ')}</p>
    {result && <>
      <strong>{en ? `${result.total_count} transactions` : `共 ${result.total_count} 笔`}</strong>
      {!result.total_count && <p>{en ? 'No matching transactions' : '无匹配流水'}</p>}
      <ul>{result.items.map(row => <li key={row.id}><button disabled={busy || stale} onClick={() => onInspect({ id: row.id, booking_date: row.booking_date, version: versions(result) })}>{row.booking_date} · {row.merchant} · {formatMoney(row.amount, row.currency, en ? 'en-US' : 'zh-CN')}</button></li>)}</ul>
      {result.total_count > 20 && <nav><button disabled={busy || stale || !result.offset} onClick={() => void query(result.filters, result.offset - 20, result)}>{en ? 'Previous' : '上一页'}</button><span>{result.offset / 20 + 1}</span><button disabled={busy || stale || !result.has_more} onClick={() => void query(result.filters, result.offset + 20, result)}>{en ? 'Next' : '下一页'}</button></nav>}
      <button disabled={busy} onClick={() => onLedger(result.filters)}>{en ? 'View in ledger' : '在账本查看'}</button>
    </>}
    <button aria-expanded={editing} disabled={busy} onClick={() => setEditing(v => !v)}>{en ? 'Edit filters' : '修改条件'}</button>
    {editing && <SearchForm key={JSON.stringify(current)} initial={current} copy={copy} english={en} busy={busy} onSearch={value => void query(value)} />}
    {error && <p role="alert">{error}</p>}
    {stale && <button disabled={busy} onClick={() => void query(current)}>{en ? 'Query again' : '重新查询'}</button>}
    {unsaved && <p role="status">{en ? 'Filters not saved' : '条件未保存'} <button disabled={busy} onClick={() => void save(current)}>{en ? 'Retry saving' : '重试保存'}</button></p>}
  </section>
}
