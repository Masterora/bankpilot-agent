/**
 * 文件职责：统一账本、关系核对与总览的日期选择契约。
 * 主要内容：中英文标签与受控开始/结束日期输入。
 * 关键边界：期间由工作区持有；本组件不请求接口、不计算金额。
 */
import { useId } from 'react'
import { currentPeriod, validPeriod } from './period'
import type { ReviewPeriod } from './period'

export function PeriodFilter({ period, onChange, english }: {
  period: ReviewPeriod; onChange: (period: ReviewPeriod) => void; english: boolean
}) {
  const errorId = useId()
  const invalid = !validPeriod(period)
  const month = currentPeriod()
  const previousEnd = new Date(`${month.start}T00:00:00Z`)
  previousEnd.setUTCDate(0)
  const end = previousEnd.toISOString().slice(0, 10)
  const presets = [
    { label: english ? 'This month' : '本月', value: month },
    { label: english ? 'Last month' : '上月', value: { start: `${end.slice(0, 7)}-01`, end } },
  ]
  return <div className="period-filter">
    <div className="period-presets" role="group" aria-label={english ? 'Quick period' : '常用期间'}>
      {presets.map(({ label, value }) => <button key={label} type="button" aria-pressed={period.start === value.start && period.end === value.end} onClick={() => onChange(value)}>{label}</button>)}
    </div>
    <label>{english ? 'From' : '开始日期'}<input type="date" aria-invalid={invalid} aria-describedby={invalid ? errorId : undefined} value={period.start} onChange={(event) => onChange({ ...period, start: event.target.value })} /></label>
    <label>{english ? 'To' : '结束日期'}<input type="date" aria-invalid={invalid} aria-describedby={invalid ? errorId : undefined} value={period.end} onChange={(event) => onChange({ ...period, end: event.target.value })} /></label>
    {invalid && <span id={errorId} className="error" role="alert">{english ? 'Choose an ordered period of up to 366 days.' : '请选择起止有序且不超过 366 天的期间。'}</span>}
  </div>
}
