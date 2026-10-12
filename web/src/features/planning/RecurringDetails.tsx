/**
 * 文件职责：展示固定支出计划详情与操作入口。
 * 主要内容：逐期核对、计划状态、未来配置修订及相关确认。
 * 关键边界：确认状态按项目隔离；历史配置不能由界面直接覆盖。
 */
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

type Confirmation = {
  id: string
  version: number
  serverDate: string
  date: string
  action: 'status' | 'cancel-status' | 'cancel-revision'
  status?: RecurringItem['status']
}

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
  const [pending, setConfirmation] = useState<Confirmation | null>(null)
  const confirmation = pending?.id === item.id && pending.version === item.version &&
    pending.serverDate === item.server_date ? pending : null
  const disabled = state.busy || state.loading || hasDraft
  function confirm(action: Confirmation['action'], date: string, status?: RecurringItem['status']) {
    setConfirmation({ id: item.id, version: item.version, serverDate: item.server_date, action, date, status })
  }
  async function submitConfirmation() {
    if (!confirmation || disabled) return
    const { id, version, date, action, status } = confirmation
    if (await state.perform(() => action === 'cancel-status'
      ? api.cancelRecurringStatus(id, date, version)
      : action === 'cancel-revision'
        ? api.cancelRecurringRevision(id, date, version)
        : api.recurringStatus(id, status!, version, date))) setConfirmation(null)
  }
  const [effectiveDate, setEffectiveDate] = useState(item.server_date)
  const [targetStatus, setTargetStatus] = useState<'active' | 'paused'>('paused')
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
      <p>{t('当前状态', 'Current status')} · {item.current_status === 'active' ? t('跟踪中', 'Active') : item.current_status === 'paused' ? t('已暂停', 'Paused') : t('已结束', 'Ended')}</p>
      {item.latest_effective_month.slice(0, 7) > state.month && (
        <p className="planning-hint">
          {t('已有后续配置，生效月份：', 'Scheduled configuration begins: ')}
          {item.latest_effective_month.slice(0, 7)}
        </p>
      )}
      <details className="scheduled-changes">
        <summary>{t('暂停与恢复历史', 'Pause and resume history')} · {item.status_changes.length}</summary>
        <p>{item.status_known_from
          ? t(`可靠状态历史自 ${item.status_known_from} 起；此前沿用旧状态。`, `Status history is known from ${item.status_known_from}; earlier dates use the legacy state.`)
          : t('旧计划未保存历史，无法还原以前的暂停区间。', 'This legacy plan has no recorded pause history.')}</p>
        {item.status_changes.map(change => <div className="planning-confirm" key={change.effective_date}>
          <p>{change.effective_date} · {change.status === 'active' ? t('恢复跟踪', 'Active') : change.status === 'paused' ? t('暂停跟踪', 'Paused') : t('结束', 'Ended')}
            {change.effective_date > item.server_date && ` · ${t('已安排', 'Scheduled')}`}</p>
          {change.effective_date > item.server_date && <button disabled={disabled}
            onClick={() => confirm('cancel-status', change.effective_date)}>{t('取消状态变更', 'Cancel status change')}</button>}
          {confirmation?.action === 'cancel-status' && confirmation.date === change.effective_date && <div className="planning-actions">
            <button disabled={disabled} onClick={() => void submitConfirmation()}>{t('确认取消', 'Confirm cancellation')}</button>
            <button disabled={disabled} onClick={() => setConfirmation(null)}>{t('保留', 'Keep')}</button>
          </div>}
        </div>)}
      </details>
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
              {item.current_status !== 'ended' && (
                <div className="planning-actions">
                  <button
                    disabled={disabled}
                    onClick={() => editRevision(item, revision)}
                  >
                    {t('修改这次变更', 'Edit change')}
                  </button>
                  <button
                    disabled={disabled}
                    onClick={() => confirm('cancel-revision', revision.effective_month)}
                  >
                    {t('取消这次变更', 'Cancel change')}
                  </button>
                </div>
              )}
              {confirmation?.action === 'cancel-revision' && confirmation.date === revision.effective_month && (
                <div>
                  <p>
                    {t(
                      '取消后继续使用此前的计划，其他已安排变更保留。',
                      'The preceding configuration continues; other scheduled changes are retained.',
                    )}
                  </p>
                  <button
                    disabled={disabled}
                    onClick={() => void submitConfirmation()}
                  >
                    {t('确认取消变更', 'Confirm cancellation')}
                  </button>
                  <button disabled={disabled} onClick={() => setConfirmation(null)}>
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
      {item.current_status !== 'ended' && (
        <details className="recurring-settings">
          <summary>{t('管理计划', 'Manage plan')}</summary>
          <label>{t('状态生效日期', 'Status effective date')}<input type="date" value={effectiveDate} min={item.server_date} max="9998-12-31" disabled={disabled} onChange={event => { setEffectiveDate(event.target.value); setConfirmation(null) }} /></label>
          <label>{t('目标状态', 'Target status')}<select value={targetStatus} disabled={disabled} onChange={event => { setTargetStatus(event.target.value as 'active' | 'paused'); setConfirmation(null) }}><option value="paused">{t('暂停跟踪', 'Paused')}</option><option value="active">{t('恢复跟踪', 'Active')}</option></select></label>
          <p>{t('按日生效；同日以最后一次确认状态为准，未来变更可取消。', 'Changes apply by date. The last confirmed status on a day applies; future changes can be cancelled.')}</p>
          <div className="planning-actions">
            <IconButton
              icon="edit"
              label={`${t('修改', 'Edit')} · ${item.name}`}
              disabled={disabled}
              onClick={() => edit(item)}
            />
            <button
              disabled={disabled}
              onClick={() =>
                confirm('status', effectiveDate, targetStatus)
              }
            >
              {t('安排状态变更', 'Schedule status change')}
            </button>
            <button disabled={disabled} onClick={() => confirm('status', effectiveDate, 'ended')}>
              {t('结束', 'End')}
            </button>
          </div>
        </details>
      )}
      {confirmation?.action === 'status' && (
        <div className="planning-confirm">
          <span>
            {t(
              `${confirmation.date} 起${confirmation.status === 'active' ? '恢复跟踪' : confirmation.status === 'paused' ? '暂停跟踪' : '永久结束'}；已有核对记录保留。`,
              `From ${confirmation.date}: ${confirmation.status}. Existing review records are retained.`,
            )}
          </span>
          <button disabled={disabled} onClick={() => void submitConfirmation()}>
            {t('确认状态变更', 'Confirm status change')}
          </button>
          <button disabled={disabled} onClick={() => setConfirmation(null)}>
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
