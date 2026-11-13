/** 提供交易结果的本地化展示工具。
 * 格式化只影响界面展示，不改变 API 返回的原始值。
 */

import type { Locale } from './i18n'
import type { Transaction } from './types'

/** 按设备时区展示时间到秒；不改变账务日期或业务账期。 */
export function formatTimestamp(value: string, locale: Locale): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(date)
}

/** 源数据没有时间精度时仅显示账务日期，不将补零时间作为真实时间。 */
export function formatTransactionTime(
  item: Pick<Transaction, 'time_precision' | 'occurred_at' | 'booking_date'>,
  locale: Locale,
): string {
  if (item.time_precision === 'timestamp') return formatTimestamp(item.occurred_at, locale)
  return `${item.booking_date} · ${item.time_precision === 'date' ? (locale === 'en-US' ? 'Date only' : '仅日期') : locale === 'en-US' ? 'Time unknown' : '时间未知'}`
}

export function formatMoney(amount: string, currency: string, locale: Locale): string {
  const decimal = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount)
  if (!decimal) return '—'
  const [, sign, integer, fraction = ''] = decimal
  // Decimal 字符串不能经过 Number；汇总金额也可能超出安全整数范围。
  const whole = BigInt(`${sign}${integer}`)
  const signedWhole = sign && whole === 0n ? -0 : whole
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.max(2, fraction.length),
  })
    .formatToParts(signedWhole)
    .map((part) => (part.type === 'fraction' ? fraction.padEnd(2, '0') : part.value))
    .join('')
}
