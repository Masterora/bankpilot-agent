/**
 * 文件职责：提供交易结果的本地化展示工具。
 *
 * 主要内容：
 * - `formatMoney`：按语言与币种格式化金额。
 * - `formatTimestamp` / `formatTransactionTime`：展示秒级时间并保留源精度边界。
 *
 * 关键边界：格式化只影响界面展示，不改变 API 返回的原始值。
 */

import type { Locale } from './i18n'
import type { Transaction } from './types'

/** 统一以 UTC+8 展示时间到秒，避免不同浏览器时区造成核对差异。 */
export function formatTimestamp(value: string, locale: Locale): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(date)
}

/** 源数据没有时间精度时仅显示账务日期，不将补零时间作为真实时间。 */
export function formatTransactionTime(item: Pick<Transaction, 'time_precision' | 'occurred_at' | 'booking_date'>, locale: Locale): string {
  if (item.time_precision === 'timestamp') return formatTimestamp(item.occurred_at, locale)
  return `${item.booking_date} · ${item.time_precision === 'date' ? (locale === 'en-US' ? 'Date only' : '仅日期') : (locale === 'en-US' ? 'Time unknown' : '时间未知')}`
}

export function formatMoney(amount: string, currency: string, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(Number(amount))
}
