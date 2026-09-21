/** 文件职责：月度分类预算设置、复制与账务证据下钻；金额计算全部来自服务端。 */
import { monthPeriod } from '../../shared/period'
import { BudgetDetails } from './BudgetDetails'
import { BudgetEditor } from './BudgetEditor'
import type { BudgetEditorStart } from './BudgetEditor'

import { useEffect, useState } from 'react'
import { useUnsavedChanges } from '../../shared/useUnsavedChanges'
import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { TransactionCategory } from '../../types'
import { EmptyContent, IconButton, LoadingIndicator, PageHeader } from '../../shared/ui'
import type { LedgerEntry } from '../ledger/LedgerPage'
import { usePlanningFocus } from './usePlanningFocus'
import type { BudgetItem } from './types'
import { usePlanningMonth } from './usePlanningMonth'

export function BudgetsPage({
  copy,
  locale,
  month,
  onMonthChange,
  active,
  focusTarget,
  onInspect,
  onDraftChange,
  onSaved,
  externalRevision = 0,
}: {
  copy: Messages
  locale: Locale
  month: string
  onMonthChange: (month: string) => void
  active: boolean
  focusTarget: string
  onInspect: (entry: LedgerEntry) => void
  onDraftChange: (dirty: boolean) => void
  onSaved: () => void
  externalRevision?: number
}) {
  const english = locale === 'en-US'
  const state = usePlanningMonth(api.budgets, month, english, active, onSaved, externalRevision)
  usePlanningFocus(focusTarget, state.loading, active)
  const [editor, setEditor] = useState<BudgetEditorStart | null>(null)
  const [editorVisible, setEditorVisible] = useState(false)
  const [selected, setSelected] = useState('')
  const [confirmDelete, setConfirmDelete] = useState('')
  const formOpen = editor !== null
  useEffect(() => {
    onDraftChange(formOpen)
  }, [formOpen, onDraftChange])
  useUnsavedChanges(formOpen)
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  const key = (item: Pick<BudgetItem, 'category' | 'currency'>) =>
    `${item.category}:${item.currency}`
  function edit(item: BudgetItem | null, target?: Pick<BudgetItem, 'category' | 'currency'>) {
    const category =
      item?.category ??
      target?.category ??
      (Object.keys(copy.categoryLabels) as TransactionCategory[]).find(
        (value) =>
          value !== 'income' &&
          !state.data?.items.some(
            (budget) => budget.category === value && budget.currency === 'CNY',
          ),
      ) ??
      'dining'
    const currency = item?.currency ?? target?.currency ?? 'CNY'
    const existing =
      item ??
      state.data?.items.find(
        (budget) => budget.category === category && budget.currency === currency,
      ) ??
      null
    setEditor({ item: existing, category, currency, choosingTarget: item === null })
    setSelected('')
    setEditorVisible(true)
  }
  async function remove(item: BudgetItem) {
    if (
      await state.perform(() =>
        api.deleteBudget({
          month: `${state.month}-01`,
          category: item.category,
          currency: item.currency,
          expected_version: item.version,
          budget_id: item.id,
        }),
      )
    ) {
      setConfirmDelete('')
      if (selected === key(item)) setSelected('')
    }
  }

  return (
    <section className="product-page planning-page">
      <PageHeader copy={copy} page="budgets" />
      <div className="report-toolbar">
        <label>
          {t('预算月份', 'Month')}
          <input
            type="month"
            min="1900-01"
            max="9998-12"
            value={state.month}
            disabled={state.busy || formOpen}
            onChange={(e) => {
              onMonthChange(e.target.value)
              setSelected('')
              setConfirmDelete('')
            }}
          />
        </label>
        <button
          className="primary"
          disabled={state.busy || state.loading || !state.data || formOpen}
          onClick={() => edit(null)}
        >
          {t('设置预算', 'Set budget')}
        </button>
        {formOpen && (
          <button onClick={() => setEditorVisible(true)}>
            {t('继续编辑草稿', 'Continue draft')}
          </button>
        )}
        <button
          disabled={state.busy || state.loading || formOpen}
          onClick={() =>
            void state.perform(
              () => api.copyBudgets(state.month),
              ({ copied, source_count }) =>
                copied
                  ? t(
                      `已复制 ${copied} 项预算，已有额度保持不变`,
                      `Copied ${copied} budgets; existing limits unchanged`,
                    )
                  : source_count === 0
                    ? t('上月没有可复制的预算', 'No budgets in the previous month')
                    : t(
                        '本月已包含上月所有预算，无需复制',
                        'All previous budgets already exist this month',
                      ),
            )
          }
        >
          {t('复制上月', 'Copy previous month')}
        </button>
        <IconButton
          icon="refresh"
          label={t('刷新', 'Refresh')}
          disabled={state.busy || state.loading}
          onClick={() => void state.refresh()}
        />
      </div>
      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}
      {state.notice && <p role="status">{state.notice}</p>}
      {state.loading && <LoadingIndicator label={t('正在读取预算', 'Loading budgets')} />}
      {editor && (
        <BudgetEditor
          state={state}
          copy={copy}
          locale={locale}
          active={active}
          open={editorVisible}
          initial={editor}
          onHide={() => setEditorVisible(false)}
          onDone={() => setEditor(null)}
        />
      )}
      {!state.loading && !state.error && state.data && !state.data.items.length && (
        <EmptyContent
          kind="budgets"
          title={t('本月尚未设置预算', 'No budgets this month')}
        />
      )}
      {state.data && state.data.coverage.every((row) => row.transaction_count === 0) && (
        <p className="scope-note">
          {t(
            '本月尚未导入流水，显示为零不代表实际没有支出。',
            'No transactions imported this month. Zero does not mean no actual spending.',
          )}
        </p>
      )}
      {!!state.data?.coverage.length && (
        <section className="budget-coverage">
          {state.data.coverage.map((row) => (
            <div className="coverage-row" key={row.currency}>
              <strong>{row.currency}</strong>
              <dl>
                <div>
                  <dt>{t('预算额度', 'Limits')}</dt>
                  <dd>{money(row.limit, row.currency)}</dd>
                </div>
                <div>
                  <dt>{t('预算内支出', 'Budgeted spending')}</dt>
                  <dd>{money(row.budgeted_spent, row.currency)}</dd>
                </div>
                <div>
                  <dt>{t('未设预算支出', 'Unbudgeted spending')}</dt>
                  <dd>{money(row.unbudgeted_spent, row.currency)}</dd>
                </div>
              </dl>
              <details className="coverage-source">
                <summary>{t('数据来源', 'Source')}</summary>
                <p>
                  {row.transaction_count} {t('笔流水', 'transactions')} · {t('截至', 'Through')}{' '}
                  {row.latest_transaction_date ?? '—'}
                </p>
              </details>
            </div>
          ))}
        </section>
      )}
      <div className="budget-list">
        {state.data?.items
          .slice()
          .sort((a, b) => {
            const rank = (item: BudgetItem) =>
              item.overspent ? 0 : Number(item.spent) >= Number(item.amount) * 0.8 ? 1 : 2
            return (
              rank(a) - rank(b) ||
              a.category.localeCompare(b.category) ||
              a.currency.localeCompare(b.currency)
            )
          })
          .map((item) => (
            <article
              className={`planning-card budget-row${item.overspent ? ' is-over' : ''}`}
              key={key(item)}
              id={`budget-${item.category}-${item.currency}`}
              tabIndex={-1}
            >
              <header>
                <h2>{copy.categoryLabels[item.category]}</h2>
                <span>{item.currency}</span>
              </header>
              <strong className="planning-amount">{money(item.spent, item.currency)}</strong>
              <p>
                {t('预算', 'Budget')} {money(item.amount, item.currency)}
              </p>
              <progress
                max="100"
                value={Math.max(0, Math.min(100, (Number(item.spent) / Number(item.amount)) * 100))}
                aria-label={t('预算使用比例', 'Budget usage')}
              />
              <p className={item.overspent ? 'budget-balance is-over' : 'budget-balance'}>
                {item.remaining === '0.00'
                  ? t('额度已用完', 'Limit reached')
                  : item.overspent
                    ? t('超出', 'Over by')
                    : t('剩余', 'Remaining')}{' '}
                {item.remaining !== '0.00' &&
                  money(
                    item.overspent ? item.remaining.replace('-', '') : item.remaining,
                    item.currency,
                  )}
              </p>
              <small>
                {t('已使用', 'Used')}{' '}
                {Math.max(0, (Number(item.spent) / Number(item.amount)) * 100).toFixed(0)}%
              </small>
              {!state.data?.coverage.find((row) => row.currency === item.currency)
                ?.transaction_count && (
                <small>
                  {t(
                    '该币种本月尚无已导入流水',
                    'No imported transactions in this currency this month',
                  )}
                </small>
              )}
              <div className="planning-actions">
                <button
                  disabled={state.busy}
                  aria-pressed={selected === key(item)}
                  onClick={() => setSelected(selected === key(item) ? '' : key(item))}
                >
                  {t('明细', 'Details')} · {item.transaction_count}
                </button>
                <IconButton
                  icon="edit"
                  label={`${t('修改', 'Edit')} · ${copy.categoryLabels[item.category]} · ${item.currency}`}
                  disabled={state.busy || formOpen}
                  onClick={() => edit(item)}
                />
                <IconButton
                  icon="delete"
                  label={`${t('删除', 'Delete')} · ${copy.categoryLabels[item.category]} · ${item.currency}`}
                  disabled={state.busy || formOpen}
                  onClick={() => setConfirmDelete(key(item))}
                />
              </div>
              {confirmDelete === key(item) && (
                <div className="planning-confirm">
                  <span>
                    {t(
                      '删除预算？流水不受影响。',
                      'Delete this budget? Transactions are retained.',
                    )}
                  </span>
                  <button disabled={state.busy} onClick={() => void remove(item)}>
                    {t('确认删除', 'Confirm delete')}
                  </button>
                  <button disabled={state.busy} onClick={() => setConfirmDelete('')}>
                    {t('取消', 'Cancel')}
                  </button>
                </div>
              )}
            </article>
          ))}
      </div>
      {!!state.data?.unbudgeted.length && (
        <section className="planning-evidence unbudgeted-spending">
          <h2>{t('有支出但未设预算', 'Spending without a budget')}</h2>
          <div className="planning-grid">
            {state.data.unbudgeted.map((item) => (
              <article
                className="planning-card"
                key={key(item)}
                id={`budget-${item.category}-${item.currency}`}
                tabIndex={-1}
              >
                <h3>
                  {copy.categoryLabels[item.category]} · {item.currency}
                </h3>
                <p>{money(item.spent, item.currency)}</p>
                <div className="planning-actions">
                  <button
                    disabled={state.busy || formOpen}
                    onClick={() => {
                      edit(null, item)
                    }}
                  >
                    {t('设置预算', 'Set budget')}
                  </button>
                  {item.category === 'other' && (
                    <button
                      className="primary"
                      onClick={() =>
                        onInspect({
                          category: item.category,
                          currency: item.currency,
                          period: monthPeriod(state.month)!,
                        })
                      }
                    >
                      {t('先核对分类', 'Review category first')}
                    </button>
                  )}
                  <button
                    aria-pressed={selected === key(item)}
                    onClick={() => setSelected(selected === key(item) ? '' : key(item))}
                  >
                    {t('明细', 'Details')} · {item.transaction_count}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      <details className="inline-note">
        <summary>{t('计算口径', 'Calculation basis')}</summary>
        <p>
          {t(
            '按已导入账单计算 · 排除已确认重复与本人转账 · 退款冲减到账月的原消费分类',
            'Imported ledger · Confirmed duplicates and transfers excluded · Refunds reduce the original category in the receipt month',
          )}
        </p>
      </details>
      {selected && state.data && (
        <BudgetDetails
          data={state.data}
          month={state.month}
          selected={selected}
          active={active}
          copy={copy}
          locale={locale}
          onClose={() => setSelected('')}
          onInspect={onInspect}
        />
      )}
    </section>
  )
}
