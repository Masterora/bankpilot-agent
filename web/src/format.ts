/**
 * 文件职责：提供交易结果的本地化展示工具。
 *
 * 主要内容：
 * - `formatMoney`：按语言与币种格式化金额。
 * - `formatDate`：按语言格式化不受浏览器时区影响的账务日期。
 *
 * 关键边界：格式化只影响界面展示，不改变 API 返回的原始值。
 */

import type { Locale } from './i18n'

export function formatMoney(amount: string, currency: string, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(Number(amount))
}

export function formatDate(value: string, locale: Locale): string {
  const [year, month, day] = value.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(year, month - 1, day))
}
