/** 预算证据侧栏：呈现服务端金额及退款原消费，提供账本核对入口。 */
import type { Locale, Messages } from '../../i18n'
import { formatMoney } from '../../format'
import { DetailPanel } from '../../shared/DetailPanel'
import type { TransactionCategory } from '../../types'
import type { BudgetWorkspace, BudgetItem } from './types'
import type { LedgerEntry } from '../agent/LedgerPage'
import { monthPeriod } from '../../shared/period'

export function BudgetDetails({
  data,
  month,
  selected,
  active,
  copy,
  locale,
  onClose,
  onInspect,
}: {
  data: BudgetWorkspace
  month: string
  selected: string
  active: boolean
  copy: Messages
  locale: Locale
  onClose: () => void
  onInspect: (entry: LedgerEntry) => void
}) {
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const money = (value: string, unit: string) => formatMoney(value, unit, locale)
  const key = (item: Pick<BudgetItem, 'category' | 'currency'>) =>
    `${item.category}:${item.currency}`
  const evidence = data.evidence.filter((item) => key(item) === selected)
  const selectedCoverage = data.coverage.find((row) => row.currency === selected.split(':')[1])
  return (
    <DetailPanel
      open={active}
      title={`${month} · ${copy.categoryLabels[selected.split(':')[0] as TransactionCategory]} · ${selected.split(':')[1]}`}
      closeLabel={t('关闭', 'Close')}
      onClose={() => onClose()}
    >
      <section className="planning-evidence">
        <h3>
          {t('预算计算明细', 'Budget evidence')} · {evidence.length}
        </h3>
        <p>
          {t('计入支出', 'Spending')}:{' '}
          {money(
            data.spending.find((item) => key(item) === selected)?.spent ?? '0.00',
            selected.split(':')[1],
          )}
        </p>
        <button
          onClick={() => {
            const row = data.evidence.find((item) => key(item) === selected)
            const period = monthPeriod(month)
            if (row && period) {
              onClose()
              onInspect({ category: row.category, currency: row.currency, period })
            }
          }}
        >
          {t('到账本核对或修改分类', 'Review or recategorize in ledger')}
        </button>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {[
                  t('日期', 'Date'),
                  t('商户 / 账户', 'Merchant / Account'),
                  t('计入支出', 'Contribution'),
                  t('依据', 'Evidence'),
                ].map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evidence.map((item) => (
                <tr key={item.transaction_id}>
                  <td>{item.booking_date}</td>
                  <td>
                    {item.merchant}
                    <small>{item.account_name}</small>
                  </td>
                  <td>{money(item.contribution, item.currency)}</td>
                  <td>
                    <details>
                      <summary>
                        {item.purchase ? t('退款抵减', 'Refund') : t('支出', 'Expense')}
                      </summary>
                      <small>{item.transaction_id}</small>
                      {item.purchase && (
                        <small>
                          {t('原消费', 'Purchase')}: {item.purchase.booking_date} ·{' '}
                          {item.purchase.merchant} · {money(item.purchase.amount, item.currency)} ·{' '}
                          {item.purchase.account_name}
                          <br />
                          {item.purchase.id}
                        </small>
                      )}
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!evidence.length && (
          <p>
            {!selectedCoverage?.transaction_count
              ? t(
                  '本月尚未导入流水，暂不能判断实际支出。',
                  'No imported transactions this month; spending is unknown.',
                )
              : t('该分类本月暂无计入流水。', 'No contributing transactions this month.')}
          </p>
        )}
      </section>
    </DetailPanel>
  )
}
