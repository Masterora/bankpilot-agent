/** Server-calculated preview, explicit confirmation and frozen recovery receipt. */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { DetailPanel } from '../../shared/DetailPanel'
import { planningError } from './errors'
import type { BudgetCarryPreview, BudgetItem } from './types'

export function BudgetCarry({ month, copy, locale, active, currentItems, onReceipt, onClose, onSaved }: {
  month: string; copy: Messages; locale: Locale; active: boolean
  currentItems: BudgetItem[] | undefined
  onReceipt: (month: string) => void
  onClose: () => void; onSaved: () => Promise<void>
}) {
  const en = locale === 'en-US'
  const t = (zh: string, english: string) => en ? english : zh
  const [preview, setPreview] = useState<BudgetCarryPreview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const operation = useRef<string | null>(null)
  const writing = useRef(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    let current = true
    setLoading(true); setError(''); setPreview(null)
    api.budgetCarryPreview(month).then(result => {
      if (current) {
        setPreview(result); operation.current = crypto.randomUUID()
        if (result.applied) onReceipt(result.month.slice(0, 7))
      }
    }).catch(cause => { if (current) setError(planningError(cause, en)) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [month, attempt, en, onReceipt])
  async function confirm() {
    if (!preview || preview.applied || !operation.current || writing.current) return
    writing.current = true; setBusy(true); setError('')
    try {
      const result = await api.confirmBudgetCarry({ month: preview.month, fingerprint: preview.fingerprint, operation_id: operation.current })
      if (!alive.current) return
      setPreview(result)
      if (result.applied) onReceipt(result.month.slice(0, 7))
      await onSaved()
    } catch (cause) { if (alive.current) setError(planningError(cause, en)) }
    finally { writing.current = false; if (alive.current) setBusy(false) }
  }
  return <DetailPanel title={preview?.applied ? t('结转回执', 'Carryover receipt') : t('预算结转', 'Budget carryover')} open={active} onClose={() => { if (!busy) onClose() }} closeLabel={t('关闭', 'Close')}>
    {loading && <p role="status">{t('正在计算…', 'Calculating…')}</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <>
      <p>{preview.source_month.slice(0, 7)} → {preview.month.slice(0, 7)}</p>
      {preview.applied
        ? <p role="status">{t('已结转。以下为当时回执；后续手动修改预算不会改写此记录。', 'Carried over. This is the frozen receipt; later budget edits do not change it.')}</p>
        : <p className="scope-note">{t('根据已导入账单结转剩余额度。超支不结转，负支出按零计算；本月未设额度时以上月额度为基础。每月仅可确认一次，确认后不会随历史账单变化重算。', 'Carry remaining limits using imported statements. Overspending is not carried; negative spending counts as zero. Missing target budgets use the prior limit as their base. Confirm once per month; historical ledger changes do not recalculate the receipt.')}</p>}
      {preview.items.some(item => item.source_transaction_count === 0) && <p role={preview.applied ? undefined : 'alert'}>{preview.applied
        ? t('当时部分币种上月没有已导入流水，回执不代表账期完整。', 'Some currencies had no imported transactions in the source month. The receipt does not prove complete statement coverage.')
        : t('部分币种上月没有导入流水，请核对账单完整性后确认。', 'Some currencies have no imported transactions in the source month. Check statement coverage before confirming.')}</p>}
      {!preview.items.length && <p>{t('上月没有可结转的剩余额度。', 'No remaining budget to carry over.')}</p>}
      <div className="planning-grid">{preview.items.map(item => <article className="planning-card" key={`${item.category}:${item.currency}`}>
        <h3>{copy.categoryLabels[item.category]} · {item.currency}</h3>
        <dl className="budget-carry-amounts">
          {[
            [t('上月额度', 'Prior limit'), item.source_amount],
            [t('上月已导入净支出', 'Prior imported net spending'), item.source_spent],
            [preview.applied ? t('当时基础额度', 'Base at confirmation') : t('本月基础额度', 'Target base'), item.base_amount],
            [t('结转金额', 'Carry amount'), item.carry_amount],
            [preview.applied ? t('当时结转后额度', 'Limit after confirmation') : t('确认后额度', 'Resulting limit'), item.target_amount],
          ].map(([label, amount]) => <div key={label}><dt>{label}</dt><dd>{formatMoney(amount, item.currency, locale)}</dd></div>)}
        </dl>
        {preview.applied && <p>{t('当前预算额度', 'Current budget limit')}：{currentItems
          ? (() => {
            const current = currentItems.find(row => row.category === item.category && row.currency === item.currency)
            return current ? formatMoney(current.amount, item.currency, locale) : t('未设置', 'Not set')
          })()
          : t('尚未读取，请刷新预算页', 'Unavailable; refresh the budget page')}</p>}
      </article>)}</div>
    </>}
    <div className="planning-actions">
      {preview && !preview.applied && !!preview.items.length && <button className="primary" disabled={busy || loading} onClick={() => void confirm()}>{busy ? t('正在确认…', 'Confirming…') : t('确认结转', 'Confirm carryover')}</button>}
      {!preview?.applied && <button disabled={busy || loading} onClick={() => setAttempt(value => value + 1)}>{t('重新计算', 'Recalculate')}</button>}
      <button disabled={busy} onClick={onClose}>{t('关闭', 'Close')}</button>
    </div>
  </DetailPanel>
}
