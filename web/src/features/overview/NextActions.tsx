/**
 * 文件职责：展示选定月份可处理的规划事项。
 * 主要内容：读取预算和固定支出结果，展示待处理摘要并提供对应页面定位入口。
 * 关键边界：单项失败不隐藏其他结果；只展示服务端结果，不生成账本写入。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { formatMoney } from '../../format'
import { currentPeriod } from '../../shared/period'
import { LoadingIndicator } from '../../shared/ui'
import type { Messages } from '../../i18n'
import type { BudgetWorkspace, RecurringWorkspace } from '../planning/types'

interface Props {
  revision: number
  month: string
  english: boolean
  copy: Messages
  onPlanning: (page: 'budgets' | 'recurring', month: string, target?: string) => void
}
export function NextActions({ month: initialMonth, english, copy, onPlanning, revision }: Props) {
  const [month, setMonth] = useState(initialMonth)
  const [budgets, setBudgets] = useState<BudgetWorkspace | null>(null)
  const [recurring, setRecurring] = useState<RecurringWorkspace | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let current = true
    setLoading(true)
    setFailed(false)
    setBudgets(null)
    setRecurring(null)
    Promise.allSettled([api.budgets(month), api.recurring(month)]).then(([budget, recurring]) => {
      if (!current) return
      if (budget.status === 'fulfilled') setBudgets(budget.value)
      if (recurring.status === 'fulfilled') setRecurring(recurring.value)
      setFailed(budget.status === 'rejected' || recurring.status === 'rejected')
      setLoading(false)
    })
    return () => {
      current = false
    }
  }, [month, attempt, revision])
  const t = (zh: string, en: string) => (english ? en : zh)
  const today = currentPeriod().end
  const charges =
    recurring?.items
      .flatMap((item) =>
        item.occurrences
          .filter(
            (occurrence) =>
              !occurrence.skipped && (!occurrence.transaction || !occurrence.transaction.eligible),
          )
          .map((occurrence) => ({ item, occurrence })),
      )
      .sort((a, b) => a.occurrence.due_date.localeCompare(b.occurrence.due_date)) ?? []
  // Comparing percentages only determines presentation priority, never stored amounts.
  const limits =
    budgets?.items
      .filter((item) => Number(item.spent) / Number(item.amount) >= 0.8)
      .sort(
        (a, b) => Number(b.overspent) - Number(a.overspent) || a.category.localeCompare(b.category),
      ) ?? []
  return (
    <section className="next-actions" aria-label={t('需要关注', 'Needs attention')}>
      <header>
        <h2>{t('本月关注', 'Monthly review')}</h2>
        <label>
          <span className="visually-hidden">{t('月度提醒月份', 'Monthly reminders')}</span>
          <input
            type="month"
            min="1900-01"
            max="9998-12"
            value={month}
            onChange={(event) => {
              if (/^\d{4}-\d{2}$/.test(event.target.value)) setMonth(event.target.value)
            }}
          />
        </label>
      </header>
      {loading && <LoadingIndicator label={t('正在读取待办', 'Loading next actions')} />}
      {failed && (
        <p role="alert">
          {t(
            '部分待办暂时无法读取，可进入对应页面查看原因。',
            'Some actions could not be loaded. Open the relevant page for details.',
          )}{' '}
          <button onClick={() => setAttempt((value) => value + 1)}>{t('重试', 'Retry')}</button>
        </p>
      )}
      <div className="next-actions-grid">
        <article>
          <h3>{t('预算提醒', 'Budget alerts')}</h3>
          {limits.slice(0, 4).map((item) => (
            <button
              className="next-action"
              key={item.id}
              onClick={() =>
                onPlanning('budgets', month, `budget-${item.category}-${item.currency}`)
              }
            >
              <strong>
                {copy.categoryLabels[item.category]} ·{' '}
                {item.overspent
                  ? t('已超预算', 'Over budget')
                  : item.remaining === '0.00'
                    ? t('额度已用完', 'Limit reached')
                    : t('接近额度', 'Near limit')}
              </strong>
              <span>
                {formatMoney(item.spent, item.currency, english ? 'en-US' : 'zh-CN')} /{' '}
                {formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}
              </span>
            </button>
          ))}
          {budgets && !limits.length && (
            <p>
              {budgets.items.length
                ? budgets.coverage.every((row) => row.transaction_count === 0)
                  ? t(
                      '本月尚无已导入流水，已保留预算额度',
                      'No imported transactions this month; budget limits retained',
                    )
                  : t(
                      '已设预算分类暂未达到额度的 80%',
                      'Set categories are below 80% of their limits',
                    )
                : t(
                    '尚未设置预算',
                    'Choose a category to start tracking a budget',
                  )}
            </p>
          )}
          <button className="text-action" onClick={() => onPlanning('budgets', month)}>
            {t('全部预算', 'All budgets')}
          </button>
        </article>
        <article>
          <h3>{t('固定支出', 'Fixed expenses')}</h3>
          {charges.slice(0, 4).map(({ item, occurrence }) => (
            <button
              className="next-action"
              key={`${item.id}:${occurrence.due_date}`}
              onClick={() => onPlanning('recurring', month, `recurring-${item.id}`)}
            >
              <strong>
                {item.name} ·{' '}
                {occurrence.transaction
                  ? t('关联需重核', 'Review link')
                  : occurrence.due_date > today
                    ? t('即将到期', 'Upcoming')
                    : t('待核对', 'Unreviewed')}
              </strong>
              <span>
                {occurrence.due_date} ·{' '}
                {formatMoney(item.amount, item.currency, english ? 'en-US' : 'zh-CN')}
              </span>
            </button>
          ))}
          {recurring && !charges.length && (
            <p>
              {recurring.items.length
                ? t('本月暂无待核对期次', 'No pending occurrences this month')
                : t(
                    '尚无固定支出',
                    'No fixed expenses',
                  )}
            </p>
          )}
          <button className="text-action" onClick={() => onPlanning('recurring', month)}>
            {t('全部固定支出', 'All recurring')} · {charges.length}
          </button>
        </article>
      </div>
    </section>
  )
}
