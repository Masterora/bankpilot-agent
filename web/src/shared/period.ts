/**
 * 文件职责：定义工作区共享期间及其有效性规则。
 * 主要内容：UTC+8 当前月份默认范围、最大 366 天跨度校验。
 * 关键边界：只处理日期，不持有页面状态或计算账务金额。
 */
export interface ReviewPeriod { start: string; end: string }

export function currentPeriod(): ReviewPeriod {
  const end = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())
  return { start: `${end.slice(0, 7)}-01`, end }
}

export function validPeriod({ start, end }: ReviewPeriod) {
  const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString().slice(0, 10) === value
  if (!validDate(start) || !validDate(end)) return false
  const days = (Date.parse(end) - Date.parse(start)) / 86400000
  return Boolean(start && end && Number.isFinite(days) && days >= 0 && days <= 366)
}
