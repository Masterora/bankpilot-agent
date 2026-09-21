/**
 * 文件职责：提供固定支出配置编辑侧栏。
 * 主要内容：周期起点、金额账户、未来生效配置、提交状态与版本冲突提示。
 * 关键边界：只提交用户确认的配置，不执行扣款；并发和生效日期由服务端裁决。
 */
import type { Locale } from '../../i18n'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import type { Account } from '../../types'
import { currentPeriod } from '../../shared/period'
import { LoadingIndicator } from '../../shared/ui'
import type { RecurringInput, RecurringItem, RecurringWorkspace } from './types'
import type { PlanningState } from './usePlanningMonth'

export interface RecurringEditorStart {
  draft: RecurringInput
  item: RecurringItem | null
  effectiveMonth: string
  replaceRevision: boolean
}

interface Props {
  state: PlanningState<RecurringWorkspace>
  locale: Locale
  active: boolean
  open: boolean
  initial: RecurringEditorStart
  accounts: Account[]
  accountsLoading: boolean
  accountError: string
  retryAccounts: () => void
  onHide: () => void
  onCancel: () => void
  onSaved: (createdMonth?: string) => void
}

export function RecurringEditor({
  state,
  locale,
  active,
  open,
  initial,
  accounts,
  accountsLoading,
  accountError,
  retryAccounts,
  onHide,
  onCancel,
  onSaved,
}: Props) {
  const [draft, setDraft] = useState(initial.draft)
  const [editing, setEditing] = useState(initial.item)
  const [effectiveMonth, setEffectiveMonth] = useState(initial.effectiveMonth)
  const replaceRevision = initial.replaceRevision
  const latestEditing = state.data?.items.find((item) => item.id === editing?.id)
  const staleDraft = !!editing && !!state.data && latestEditing?.version !== editing.version
  function update(value: Partial<RecurringInput>) {
    setDraft((current) => ({ ...current, ...value }))
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (
      state.loading ||
      staleDraft ||
      accountsLoading ||
      accountError ||
      !accounts.some((account) => account.id === draft.account_id)
    )
      return
    const saved = await state.perform(() =>
      editing
        ? api.editRecurring({
            ...draft,
            expected_version: editing.version,
            replace_revision: replaceRevision,
            source_month: `${state.month}-01`,
            effective_month: `${effectiveMonth}-01`,
          })
        : api.createRecurring(draft),
    )
    if (saved) onSaved(editing ? undefined : draft.start_date.slice(0, 7))
  }
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  return (
    <DetailPanel
      open={active && open}
      title={
        editing
          ? t('修改固定支出', 'Edit recurring charge')
          : t('添加固定支出', 'Add recurring charge')
      }
      closeLabel={t('收起并保留草稿', 'Keep draft and close')}
      onClose={onHide}
    >
      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}
      {accountError && (
        <p role="alert">
          {accountError} <button onClick={retryAccounts}>{t('重试', 'Retry')}</button>
        </p>
      )}
      {accountsLoading && <LoadingIndicator label={t('正在读取账户', 'Loading accounts')} />}
      <form className="planning-form" onSubmit={save}>
        {staleDraft && (
          <div className="planning-confirm" role="alert">
            {latestEditing && (
              <p>
                {t('原金额', 'Original')}: {money(editing!.amount, editing!.currency)} ·{' '}
                {t('当前金额', 'Current')}: {money(latestEditing.amount, latestEditing.currency)} ·{' '}
                {t('你的输入', 'Your input')}: {draft.amount} {draft.currency}
              </p>
            )}
            <span>
              {t(
                '配置已变化，已保留输入。请核对当前卡片后再继续。',
                'Configuration changed. Your input is retained; review the current card before continuing.',
              )}
            </span>
            {latestEditing?.status !== 'ended' && latestEditing && (
              <button
                type="button"
                disabled={state.busy || state.loading || !!state.error}
                onClick={() => setEditing(latestEditing)}
              >
                {t('保留输入，按最新版本继续', 'Keep input and use latest version')}
              </button>
            )}
          </div>
        )}
        <fieldset disabled={state.busy}>
          {editing && (
            <label>
              {t('从哪个月开始', 'Starting month')}
              <input
                type="month"
                required
                min={currentPeriod().start.slice(0, 7)}
                max="9998-12"
                disabled={replaceRevision}
                value={effectiveMonth}
                onChange={(e) => setEffectiveMonth(e.target.value)}
              />
              <small>
                {t(
                  '金额、账户、商户和日期变更从此月生效；名称纠正适用于整个项目。',
                  'Financial and schedule changes apply from this month; name corrections apply to the plan.',
                )}
              </small>
            </label>
          )}
          <label>
            {t('名称', 'Name')}
            <input
              autoFocus
              required
              maxLength={100}
              value={draft.name}
              onChange={(e) => update({ name: e.target.value })}
            />
          </label>
          <label>
            {t('商户', 'Merchant')}
            <input
              required
              maxLength={160}
              value={draft.merchant}
              onChange={(e) => update({ merchant: e.target.value })}
            />
          </label>
          <label>
            {t('扣款账户', 'Account')}
            <select
              value={draft.account_id}
              onChange={(e) => {
                const account = accounts.find((a) => a.id === e.target.value)
                if (account) update({ account_id: account.id, currency: account.currency })
              }}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {a.currency}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('预计金额', 'Expected amount')} · {draft.currency}
            <input
              required
              type="number"
              min="0.01"
              max="9999999999999999.99"
              step="0.01"
              value={draft.amount}
              onChange={(e) => update({ amount: e.target.value })}
            />
          </label>
          <label>
            {t('频率', 'Frequency')}
            <select
              value={draft.cadence}
              onChange={(e) => update({ cadence: e.target.value as RecurringInput['cadence'] })}
            >
              <option value="monthly">{t('每月', 'Monthly')}</option>
              <option value="yearly">{t('每年', 'Yearly')}</option>
            </select>
          </label>
          <label>
            {t('周期起始日', 'Schedule start date')}
            <input
              required
              type="date"
              min="1900-01-01"
              max="9998-12-31"
              value={draft.start_date}
              onChange={(e) => update({ start_date: e.target.value })}
            />
          </label>
          <div className="planning-actions">
            <button
              className="primary"
              disabled={
                state.loading ||
                staleDraft ||
                accountsLoading ||
                !!accountError ||
                !accounts.some((account) => account.id === draft.account_id)
              }
            >
              {state.busy ? t('保存中…', 'Saving…') : t('保存', 'Save')}
            </button>
            <button type="button" onClick={onCancel}>
              {t('取消', 'Cancel')}
            </button>
          </div>
        </fieldset>
      </form>
    </DetailPanel>
  )
}
