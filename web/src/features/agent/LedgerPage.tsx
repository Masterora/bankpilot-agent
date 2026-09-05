/**
 * 文件职责：提供独立于 Agent 的交易账本。
 * 主要内容：日期筛选、来源账户、分类修正、JSON 导出与请求失败重试。
 * 关键边界：源字段只读；分类由服务端保存后重新读取，不依赖模型。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Messages } from '../../i18n'
import type { Transaction, TransactionCategory } from '../../types'

export function LedgerPage({ copy, english }: { copy: Messages; english: boolean }) {
  const today = new Date().toISOString().slice(0, 10)
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`)
  const [end, setEnd] = useState(today)
  const [items, setItems] = useState<Transaction[]>([])
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    let active = true
    api.ledger(start, end).then((data) => { if (active) { setItems(data.items); setState('ready') } })
      .catch(() => { if (active) setState('failed') })
    return () => { active = false }
  }, [start, end, attempt])
  async function correct(id: string, category: TransactionCategory) {
    setSaving(true)
    try { await api.correctLedgerCategory(id, category); setAttempt((value) => value + 1) }
    catch { setState('failed') }
    finally { setSaving(false) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ start, end, transactions: items }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = `bankpilot-${start}-${end}.json`; link.click()
    URL.revokeObjectURL(url)
  }
  return <section className="product-page"><header className="page-header"><h1>{english ? 'Transaction ledger' : '交易账本'}</h1><p>{english ? 'Source fields are read-only' : '原始交易只读 · 分类独立保存'}</p></header>
    <div className="import-account-grid"><label>{english ? 'From' : '开始日期'}<input type="date" value={start} onChange={(event) => { setState('loading'); setStart(event.target.value) }} /></label><label>{english ? 'To' : '结束日期'}<input type="date" value={end} onChange={(event) => { setState('loading'); setEnd(event.target.value) }} /></label></div>
    {state === 'loading' ? <p>{english ? 'Loading' : '正在读取'}</p> : state === 'failed' ? <button onClick={() => { setState('loading'); setAttempt(attempt + 1) }}>{english ? 'Request failed. Retry' : '读取或保存失败，重试'}</button> : <>
      <button disabled={!items.length} onClick={download}>{english ? 'Export selected period' : '导出所选期间'}</button>
      {!items.length ? <p>{english ? 'No transactions in this period' : '所选期间暂无交易'}</p> : <div className="import-table-wrap"><table className="import-table"><thead><tr>{(english ? ['Date', 'Account', 'Merchant', 'Amount', 'Category'] : ['日期', '账户', '商户', '金额', '分类']).map((text) => <th key={text}>{text}</th>)}</tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.booking_date}</td><td>{item.account_name}</td><td>{item.merchant}<small> {item.description}</small></td><td>{item.amount} {item.currency}</td><td><select aria-label={`${copy.categoryLabel}: ${item.merchant}`} value={item.category} disabled={saving} onChange={(event) => void correct(item.id, event.target.value as TransactionCategory)}>{Object.entries(copy.categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td></tr>)}</tbody></table></div>}
    </>}
  </section>
}
