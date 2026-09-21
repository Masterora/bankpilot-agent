/** 文件职责：手动周期项与逐期流水核对；预计金额仅展示，不写入账本。 */
import { RecurringEditor } from './RecurringEditor'
import type { RecurringEditorStart } from './RecurringEditor'
import { RecurringDetails } from './RecurringDetails'

import { Fragment, useEffect, useState } from 'react'
import { useUnsavedChanges } from '../../shared/useUnsavedChanges'
import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { Account } from '../../types'
import { newIdempotencyKey } from '../../shared/operationKey'
import { EmptyContent, IconButton, LoadingIndicator, PageHeader } from '../../shared/ui'
import { currentPeriod } from '../../shared/period'
import { usePlanningFocus } from './usePlanningFocus'
import type { RecurringInput, RecurringItem, RecurringRevision } from './types'
import { usePlanningMonth } from './usePlanningMonth'
import { planningError } from './errors'

export function RecurringPage({
  copy,
  locale,
  month,
  onMonthChange,
  active,
  seed,
  focusTarget,
  onSeedConsumed,
  onDraftChange,
  onSaved,
}: {
  copy: Messages
  locale: Locale
  month: string
  onMonthChange: (month: string) => void
  active: boolean
  seed: RecurringInput | null
  focusTarget: string
  onSeedConsumed: () => void
  onDraftChange: (dirty: boolean) => void
  onSaved: () => void
}) {
  const english = locale === 'en-US'
  const state = usePlanningMonth(api.recurring, month, english, active, onSaved)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountError, setAccountError] = useState('')
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [accountAttempt, setAccountAttempt] = useState(0)
  const [editor, setEditor] = useState<RecurringEditorStart | null>(null)
  const draft = editor?.draft ?? null
  const [editorVisible, setEditorVisible] = useState(true)
  const [selected, setSelected] = useState('')
  const [filter, setFilter] = useState('all')
  usePlanningFocus(focusTarget, state.loading, active)
  useEffect(() => {
    if (seed && !draft) {
      setEditorVisible(true)
      setEditor({
        draft: seed,
        item: null,
        effectiveMonth: month.slice(0, 7),
        replaceRevision: false,
      })
      onSeedConsumed()
    }
  }, [seed, draft, month, onSeedConsumed])
  useEffect(() => {
    onDraftChange(!!draft)
  }, [draft, onDraftChange])
  useUnsavedChanges(!!draft)
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  useEffect(() => {
    if (!active) return
    let current = true
    setAccountsLoading(true)
    setAccountError('')
    api
      .listAccounts()
      .then((response) => {
        if (current) {
          setAccounts(response.items)
          setAccountError('')
        }
      })
      .catch((error) => {
        if (current) setAccountError(planningError(error, english))
      })
      .finally(() => {
        if (current) setAccountsLoading(false)
      })
    return () => {
      current = false
    }
  }, [active, english, accountAttempt])

  function create() {
    setEditorVisible(true)
    const account = accounts[0]
    if (!account) return
    setEditor({
      item: null,
      effectiveMonth: state.month,
      replaceRevision: false,
      draft: {
        id: newIdempotencyKey(),
        name: '',
        merchant: '',
        amount: '',
        account_id: account.id,
        currency: account.currency,
        cadence: 'monthly',
        start_date: `${state.month}-01`,
      },
    })
  }
  function edit(item: RecurringItem) {
    setSelected('')
    setEditorVisible(true)
    const { id, name, merchant, account_id, currency, amount, cadence, start_date } = item
    const latest = item.latest_effective_month.slice(0, 7)
    const year = Number(latest.slice(0, 4)),
      monthNumber = Number(latest.slice(5))
    const next =
      monthNumber === 12 ? `${year + 1}-01` : `${year}-${String(monthNumber + 1).padStart(2, '0')}`
    setEditor({
      item,
      replaceRevision: false,
      draft: { id, name, merchant, account_id, currency, amount, cadence, start_date },
      effectiveMonth: [next, state.month, currentPeriod().start.slice(0, 7)].sort().at(-1)!,
    })
  }
  function editRevision(item: RecurringItem, revision: RecurringRevision) {
    setSelected('')
    setEditorVisible(true)
    const { effective_month, ...configuration } = revision
    setEditor({
      item,
      replaceRevision: true,
      draft: { id: item.id, name: item.name, ...configuration },
      effectiveMonth: effective_month.slice(0, 7),
    })
  }
  const statusOf = (item: RecurringItem) =>
    item.occurrences.some((o) => !o.skipped && (!o.transaction || !o.transaction.eligible))
      ? item.occurrences.some(
          (o) =>
            !o.skipped &&
            (!o.transaction || !o.transaction.eligible) &&
            o.due_date <= currentPeriod().end,
        )
        ? 'pending'
        : 'upcoming'
      : item.occurrences.length
        ? 'reviewed'
        : 'inactive'
  const filters = [
    ['all', t('全部', 'All')],
    ['pending', t('待核对', 'Unreviewed')],
    ['upcoming', t('即将到期', 'Upcoming')],
    ['reviewed', t('已处理', 'Reviewed')],
    ['inactive', t('本月无期次', 'No occurrence')],
  ]
  const ordered = state.data?.items.slice() ?? []
  ordered.sort(
    (a, b) =>
      (a.occurrences[0]?.due_date ?? a.next_due_date ?? '9999').localeCompare(
        b.occurrences[0]?.due_date ?? b.next_due_date ?? '9999',
      ) || a.name.localeCompare(b.name),
  )
  return (
    <section className="product-page planning-page">
      <PageHeader copy={copy} page="recurring" />
      {seed && draft && draft.id !== seed.id && (
        <div className="planning-confirm">
          <span>
            {t(
              '已保留正在编辑的内容。使用刚选的流水会替换此草稿。',
              'Your current draft is retained. Use the selected transaction to replace it.',
            )}
          </span>
          <button
            disabled={state.busy}
            onClick={() => {
              setEditorVisible(true)
              setEditor({
                item: null,
                draft: seed,
                replaceRevision: false,
                effectiveMonth: state.month,
              })
              onSeedConsumed()
            }}
          >
            {t('使用所选流水重新填写', 'Replace draft with selected transaction')}
          </button>
        </div>
      )}
      <div className="report-toolbar">
        <label>
          {t('核对月份', 'Month')}
          <input
            type="month"
            min="1900-01"
            max="9998-12"
            value={state.month}
            disabled={state.busy || !!draft}
            onChange={(e) => {
              onMonthChange(e.target.value)
            }}
          />
        </label>
        <button
          className="primary"
          disabled={state.busy || !!draft || accountsLoading || !!accountError || !accounts.length}
          onClick={create}
        >
          {t('添加固定支出', 'Add recurring charge')}
        </button>
        {draft && (
          <button onClick={() => setEditorVisible(true)}>
            {t('继续编辑草稿', 'Continue draft')}
          </button>
        )}
        <IconButton
          icon="refresh"
          label={t('刷新', 'Refresh')}
          disabled={state.busy || state.loading}
          onClick={() => {
            void state.refresh()
            setAccountAttempt((value) => value + 1)
          }}
        />
      </div>
      {accountsLoading && <LoadingIndicator label={t('正在读取账户', 'Loading accounts')} />}
      {accountError && (
        <p className="error" role="alert">
          {accountError}{' '}
          <button onClick={() => setAccountAttempt((n) => n + 1)}>{t('重试', 'Retry')}</button>
        </p>
      )}
      {!accountsLoading && !accountError && !accounts.length && (
        <p>
          {t(
            '请先导入账单建立账户，再添加固定支出。',
            'Import a statement to create an account before adding a recurring charge.',
          )}
        </p>
      )}
      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}
      {state.notice && <p role="status">{state.notice}</p>}
      {state.loading && (
        <LoadingIndicator label={t('正在读取周期项', 'Loading recurring charges')} />
      )}
      {editor && (
        <RecurringEditor
          key={`${editor.draft.id}:${editor.effectiveMonth}`}
          state={state}
          locale={locale}
          active={active}
          initial={editor}
          open={editorVisible}
          accounts={accounts}
          accountsLoading={accountsLoading}
          accountError={accountError}
          retryAccounts={() => setAccountAttempt((value) => value + 1)}
          onHide={() => setEditorVisible(false)}
          onCancel={() => setEditor(null)}
          onSaved={(createdMonth) => {
            setEditor(null)
            if (createdMonth) onMonthChange(createdMonth)
          }}
        />
      )}
      {!state.loading && !state.error && state.data && !state.data.items.length && (
        <EmptyContent
          kind="recurring"
          title={t('还没有周期项', 'No recurring charges')}
          detail={t(
            '添加房租、会员或其他固定扣款，逐月核对。',
            'Add rent, subscriptions or other recurring charges to review each month.',
          )}
        />
      )}
      <div className="relation-tabs" aria-label={t('核对状态', 'Review status')}>
        {filters.map(([value, label]) => (
          <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>
            {label} ·{' '}
            {state.data?.items.filter((item) => value === 'all' || statusOf(item) === value)
              .length ?? 0}
          </button>
        ))}
      </div>
      <div className="recurring-list">
        {ordered.map((item) => (
          <Fragment key={item.id}>
            <article
              hidden={filter !== 'all' && statusOf(item) !== filter}
              className="planning-card"
              id={`recurring-${item.id}`}
              tabIndex={-1}
            >
              <header>
                <h2>{item.name}</h2>
                <span className="planning-status">
                  {item.status === 'active'
                    ? t('跟踪中', 'Active')
                    : item.status === 'paused'
                      ? t('已暂停', 'Paused')
                      : t('已结束', 'Ended')}
                </span>
              </header>
              <strong className="planning-amount">
                {money(item.amount, item.currency)}{' '}
                <small>/ {item.cadence === 'monthly' ? t('月', 'month') : t('年', 'year')}</small>
              </strong>
              <p>
                {item.merchant} ·{' '}
                {accounts.find((a) => a.id === item.account_id)?.name ?? item.currency}
              </p>
              <p>
                {item.occurrences
                  .map(
                    (o) =>
                      `${o.due_date} · ${o.skipped ? t('本期未发生', 'No charge') : o.transaction?.eligible ? t('已核对', 'Linked') : o.transaction ? t('关联需重核', 'Review link') : o.due_date > currentPeriod().end ? t('即将到期', 'Upcoming') : t('待核对', 'Unreviewed')}`,
                  )
                  .join(' / ') ||
                  (item.next_due_date
                    ? `${t('下次', 'Next')} ${item.next_due_date}`
                    : t('未安排扣款', 'No scheduled charge'))}
              </p>
              <button onClick={() => setSelected(item.id)}>
                {statusOf(item) === 'pending' ? t('核对', 'Review') : t('详情', 'Details')}
              </button>
            </article>
            {selected === item.id && (
              <RecurringDetails
                key={item.id}
                state={state}
                item={item}
                locale={locale}
                active={active}
                accounts={accounts}
                hasDraft={!!draft}
                onClose={() => setSelected('')}
                edit={edit}
                editRevision={editRevision}
                nextAvailable={ordered.some(
                  (next) => next.id !== item.id && statusOf(next) === 'pending',
                )}
                onNext={() => {
                  const next = ordered.find(
                    (next) => next.id !== item.id && statusOf(next) === 'pending',
                  )
                  if (next) {
                    setFilter('all')
                    setSelected(next.id)
                  }
                }}
              />
            )}
          </Fragment>
        ))}
      </div>
      <details className="inline-note">
        <summary>{t('跟踪说明', 'About tracking')}</summary>
        <p>
          {t(
            '这里只跟踪固定支出，不会替你开通、暂停或取消商家的扣款。',
            'Track fixed expenses here. This does not start, pause or cancel merchant payments.',
          )}
        </p>
      </details>
    </section>
  )
}
