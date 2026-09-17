/** 预算编辑侧栏：字段输入、上月参考和版本冲突的显式确认。 */
import type { Locale, Messages } from '../../i18n'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import type { TransactionCategory } from '../../types'
import type { BudgetItem, BudgetWorkspace } from './types'
import type { PlanningState } from './usePlanningMonth'

export interface BudgetEditorStart {
  item: BudgetItem | null
  category: TransactionCategory
  currency: string
  choosingTarget: boolean
}

interface Props {
  state: PlanningState<BudgetWorkspace>
  copy: Messages
  locale: Locale
  active: boolean
  open: boolean
  initial: BudgetEditorStart
  onHide: () => void
  onDone: () => void
}

export function BudgetEditor({
  state,
  copy,
  locale,
  active,
  open,
  initial,
  onHide,
  onDone,
}: Props) {
  const [editing, setEditing] = useState(initial.item)
  const [category, setCategory] = useState(initial.category)
  const [currency, setCurrency] = useState(initial.currency)
  const [amount, setAmount] = useState(initial.item?.amount ?? '')
  const choosingTarget = initial.choosingTarget
  const [reference, setReference] = useState<BudgetWorkspace | null>(null)
  const [referenceFailed, setReferenceFailed] = useState(false)
  const [referenceAttempt, setReferenceAttempt] = useState(0)
  useEffect(() => {
    if (!active || state.month === '1900-01') return
    let current = true
    const previous = new Date(`${state.month}-01T00:00:00Z`)
    previous.setUTCMonth(previous.getUTCMonth() - 1)
    setReference(null)
    setReferenceFailed(false)
    api
      .budgets(previous.toISOString().slice(0, 7))
      .then((data) => {
        if (current) setReference(data)
      })
      .catch(() => {
        if (current) setReferenceFailed(true)
      })
    return () => {
      current = false
    }
  }, [active, state.month, referenceAttempt])
  const latestBudget =
    state.data?.items.find((item) => item.category === category && item.currency === currency) ??
    null
  const changedWhileEditing =
    state.data !== null &&
    ((latestBudget?.id ?? null) !== (editing?.id ?? null) ||
      (latestBudget?.version ?? 0) !== (editing?.version ?? 0))
  function chooseTarget(nextCategory: TransactionCategory, nextCurrency: string) {
    const existing =
      state.data?.items.find(
        (item) => item.category === nextCategory && item.currency === nextCurrency,
      ) ?? null
    setCategory(nextCategory)
    setCurrency(nextCurrency)
    setEditing(existing)
    setAmount(existing?.amount ?? '')
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (changedWhileEditing || state.loading || !state.data) return
    if (
      await state.perform(() =>
        api.saveBudget({
          month: `${state.month}-01`,
          category,
          currency,
          amount,
          expected_version: editing?.version ?? 0,
          budget_id: editing?.id ?? null,
        }),
      )
    )
      onDone()
  }
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  const referenceCoverage = reference?.coverage.find((row) => row.currency === currency)
  return (
    <DetailPanel
      open={active && open}
      title={`${state.month} · ${editing ? t('修改额度', 'Edit limit') : t('设置预算', 'Set budget')}`}
      closeLabel={t('收起并保留草稿', 'Keep draft and close')}
      onClose={onHide}
    >
      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}
      <form className="planning-form" onSubmit={save}>
        {choosingTarget && editing && !changedWhileEditing && (
          <p className="planning-hint">
            {t(
              '已载入现有额度，保存后更新此预算。',
              'Existing limit loaded. Saving updates this budget.',
            )}
          </p>
        )}
        {changedWhileEditing && (
          <div className="planning-confirm" role="alert">
            <span>
              {latestBudget
                ? t(
                    `当前额度已变为 ${money(latestBudget.amount, currency)}。已保留你的输入，请核对后继续。`,
                    `The current limit is ${money(latestBudget.amount, currency)}. Your input is retained; review before continuing.`,
                  )
                : t(
                    '此预算已被删除。已保留输入，可以重新建立预算。',
                    'This budget was deleted. Your input is retained and can be used to create a new budget.',
                  )}
            </span>
            <button
              type="button"
              disabled={state.busy || state.loading || !!state.error}
              onClick={() => setEditing(latestBudget)}
            >
              {latestBudget
                ? t('保留输入，按最新版本继续', 'Keep input and use latest version')
                : t('确认重新建立', 'Confirm recreation')}
            </button>
          </div>
        )}
        {referenceFailed ? (
          <p>
            {t(
              '暂时无法读取上月参考，可直接填写额度。',
              'Previous spending unavailable; you can still set a limit.',
            )}{' '}
            <button type="button" onClick={() => setReferenceAttempt((value) => value + 1)}>
              {t('重试', 'Retry')}
            </button>
          </p>
        ) : (
          reference && (
            <p className="planning-hint">
              {t('上月支出参考', 'Previous imported spending')}:{' '}
              {!referenceCoverage?.transaction_count
                ? t('上月尚未导入流水', 'No imported transactions last month')
                : money(
                    reference.spending.find(
                      (row) => row.category === category && row.currency === currency,
                    )?.spent ?? '0.00',
                    currency,
                  )}{' '}
              · {t('仅含已导入流水', 'Imported transactions only')}
            </p>
          )
        )}
        <fieldset disabled={state.busy}>
          <label>
            {t('分类', 'Category')}
            <select
              value={category}
              disabled={!choosingTarget}
              onChange={(e) => chooseTarget(e.target.value as TransactionCategory, currency)}
            >
              {Object.entries(copy.categoryLabels)
                .filter(([value]) => value !== 'income')
                .map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
            </select>
          </label>
          <label>
            {t('币种', 'Currency')}
            <input
              required
              pattern="[A-Z]{3}"
              maxLength={3}
              value={currency}
              disabled={!choosingTarget}
              onChange={(e) => chooseTarget(category, e.target.value.toUpperCase())}
            />
          </label>
          <label>
            {t('月额度', 'Monthly limit')}
            <input
              autoFocus
              required
              type="number"
              min="0.01"
              step="0.01"
              max="9999999999999999.99"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <div className="planning-actions">
            <button
              className="primary"
              disabled={changedWhileEditing || state.loading || !state.data}
            >
              {state.busy ? t('保存中…', 'Saving…') : t('保存', 'Save')}
            </button>
            <button type="button" onClick={onDone}>
              {t('取消', 'Cancel')}
            </button>
          </div>
        </fieldset>
      </form>
    </DetailPanel>
  )
}
