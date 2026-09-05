/**
 * 文件职责：将筛选后的账本转为可阅读的 CSV。
 * 主要内容：标准列序、UTF-8 标记、文本转义与公式防护。
 * 关键边界：用于核查导出，不是来源原账单或无损备份格式。
 */
import type { Transaction } from '../../types'

/** 文本转义并阻止表格公式执行；金额字段仅接受服务端数字字符串。 */
export function ledgerCsv(items: Transaction[]): string {
  const cell = (value: string) => `"${(/^[\s]*[=+@-]/.test(value) ? `'${value}` : value).replaceAll('"', '""')}"`
  return '\ufeff' + ['Date,Account,Merchant,Amount,Currency,Category,Batch,Source row,Description', ...items.map((i) =>
    [cell(i.booking_date), cell(i.account_name), cell(i.merchant), /^-?\d+(\.\d+)?$/.test(i.amount) ? i.amount : cell(i.amount), cell(i.currency), cell(i.category), cell(i.import_batch_id ?? ''), String(i.source_row_number ?? ''), cell(i.description)].join(','))].join('\r\n')
}
