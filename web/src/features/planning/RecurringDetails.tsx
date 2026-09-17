/** 固定支出详情：期次核对、计划状态及未来配置操作；确认状态按项目隔离。 */
import type { Locale } from '../../i18n'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import { useState } from 'react'
import type { Account } from '../../types'
import { api } from '../../api'
import { IconButton } from '../../shared/ui'
import { Occurrence } from './RecurringOccurrence'
import type { RecurringItem, RecurringRevision, RecurringWorkspace } from './types'
import type { PlanningState } from './usePlanningMonth'

export function RecurringDetails({
  state,
  item,
  locale,
  active,
  accounts,
  hasDraft,
  onClose,
  edit,
  editRevision,
  onNext,
  nextAvailable,
}: {
  state: PlanningState<RecurringWorkspace>
  item: RecurringItem
  locale: Locale
  active: boolean
  accounts: Account[]
  hasDraft: boolean
  onClose: () => void
  edit: (item: RecurringItem) => void
  editRevision: (item: RecurringItem, revision: RecurringRevision) => void
  onNext: () => void
  nextAvailable: boolean
}) {
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  const [cancelRevision, setCancelRevision] = useState('')
  const [confirmation, setConfirmation] = useState('')
  async function changeStatus(item: RecurringItem, status: RecurringItem['status']) {
    if (await state.perform(() => api.recurringStatus(item.id, status, item.version)))
      setConfirmation('')
  }
  return (
    <DetailPanel
      open={active}
      title={`${state.month} · ${item.name}`}
      closeLabel={t('关闭', 'Close')}
      onClose={() => onClose()}
    >
      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}
      {state.notice && <p role="status">{state.notice}</p>}
      {item.latest_effective_month.slice(0, 7) > state.month && (
        <p className="planning-hint">
          {t('已有后续配置，生效月份：', 'Scheduled configuration begins: ')}
          {item.latest_effective_month.slice(0, 7)}
        </p>
      )}
      {!!item.future_revisions.length && (
        <details className="scheduled-changes">
          <summary>
            {t('查看已安排的变更', 'Scheduled changes')} · {item.future_revisions.length}
          </summary>
          {item.future_revisions.map((revision) => (
            <div key={revision.effective_month} className="planning-confirm">
              <p>
                {revision.effective_month.slice(0, 7)} · {money(revision.amount, revision.currency)}{' '}
                · {revision.cadence === 'monthly' ? t('每月', 'Monthly') : t('每年', 'Yearly')} ·{' '}
                {revision.merchant} · {accounts.find((a) => a.id === revision.account_id)?.name} ·{' '}
                {revision.start_date}
              </p>
              {item.status !== 'ended' && (
                <div className="planning-actions">
                  <button
                    disabled={state.busy || hasDraft}
                    onClick={() => editRevision(item, revision)}
                  >
                    {t('修改这次变更', 'Edit change')}
                  </button>
                  <button
                    disabled={state.busy || hasDraft}
                    onClick={() => setCancelRevision(`${item.id}:${revision.effective_month}`)}
                  >
                    {t('取消这次变更', 'Cancel change')}
                  </button>
                </div>
              )}
              {cancelRevision === `${item.id}:${revision.effective_month}` && (
                <div>
                  <p>
                    {t(
                      '取消后继续使用此前的计划，其他已安排变更保留。',
                      'The preceding configuration continues; other scheduled changes are retained.',
                    )}
                  </p>
                  <button
                    disabled={state.busy}
                    onClick={async () => {
                      if (
                        await state.perform(() =>
                          api.cancelRecurringRevision(
                            item.id,
                            revision.effective_month,
                            item.version,
                          ),
                        )
                      )
                        setCancelRevision('')
                    }}
                  >
                    {t('确认取消变更', 'Confirm cancellation')}
                  </button>
                  <button disabled={state.busy} onClick={() => setCancelRevision('')}>
                    {t('保留变更', 'Keep change')}
                  </button>
                </div>
              )}
            </div>
          ))}
        </details>
      )}
      {item.occurrences.map((occurrence) => (
        <Occurrence
          key={`${state.month}:${occurrence.due_date}:${item.version}`}
          item={item}
          due={occurrence.due_date}
          transaction={occurrence.transaction}
          skipped={occurrence.skipped}
          onSkip={(skipped) =>
            state.perform(() =>
              api.skipRecurring(item.id, occurrence.due_date, skipped, item.version),
            )
          }
          candidates={state.data?.candidates ?? []}
          locale={locale}
          busy={state.busy || state.loading}
          refreshKey={state.refreshKey}
          onMatch={(id) =>
            state.perform(() => api.matchRecurring(item.id, occurrence.due_date, id, item.version))
          }
        />
      ))}
      {!item.occurrences.length && (
        <p>
          {t('本月无待核对期次', 'No pending occurrence this month')} ·{' '}
          {t('下次计划日期', 'Next planned date')}{' '}
          {item.next_due_date ?? t('未安排', 'Not scheduled')}
        </p>
      )}
      {item.status !== 'ended' && (
        <details className="recurring-settings">
          <summary>{t('管理计划', 'Manage plan')}</summary>
          <div className="planning-actions">
            <IconButton
              icon="edit"
              label={`${t('修改', 'Edit')} · ${item.name}`}
              disabled={state.busy || state.loading || hasDraft}
              onClick={() => edit(item)}
            />
            <button
              disabled={state.busy}
              onClick={() =>
                void changeStatus(item, item.status === 'active' ? 'paused' : 'active')
              }
            >
              {item.status === 'active'
                ? t('暂停跟踪', 'Pause tracking')
                : t('恢复跟踪', 'Resume tracking')}
            </button>
            <button disabled={state.busy} onClick={() => setConfirmation(item.id)}>
              {t('结束', 'End')}
            </button>
          </div>
        </details>
      )}
      {confirmation === item.id && (
        <div className="planning-confirm">
          <span>
            {t(
              '结束后不再跟踪，已有核对记录保留。',
              'End tracking permanently? Linked records are retained.',
            )}
          </span>
          <button disabled={state.busy} onClick={() => void changeStatus(item, 'ended')}>
            {t('确认结束', 'Confirm end')}
          </button>
          <button disabled={state.busy} onClick={() => setConfirmation('')}>
            {t('取消', 'Cancel')}
          </button>
        </div>
      )}
      <button disabled={!nextAvailable} onClick={onNext}>
        {t('下一项待核对', 'Next unreviewed')}
      </button>
    </DetailPanel>
  )
}
