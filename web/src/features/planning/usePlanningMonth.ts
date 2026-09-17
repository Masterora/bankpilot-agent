/** 文件职责：两个规划页面的月份读取与显式写操作；迟到响应隔离，失败保留编辑内容。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../../shared/apiErrors'

const errors: Record<string, [string, string]> = {
  planning_revision_locked: [
    '该计划已生效或已有核对结果，不能改写；请安排后续变更。',
    'This configuration is effective or reviewed. Schedule a later change.',
  ],
  planning_skipped: [
    '本期已确认未发生，请先撤回该确认。',
    'Undo the skipped confirmation before linking.',
  ],
  planning_not_due: [
    '尚未到预计日期，不能确认本期未发生。',
    'Wait until the due date to confirm no charge occurred.',
  ],
  planning_stale: ['数据已变化，请刷新后重试。', 'Data changed. Refresh and retry.'],
  planning_not_found: ['记录已不存在，请刷新。', 'Record unavailable. Please refresh.'],
  planning_already_linked: [
    '流水或期次已关联，请刷新后核对。',
    'Transaction or occurrence already linked. Refresh to review.',
  ],
  planning_match_invalid: [
    '该流水不符合账户、币种或有效支出要求。',
    'Select an eligible expense in the same account and currency.',
  ],
  planning_inactive: [
    '请先恢复跟踪，再关联流水。',
    'Resume this plan before linking a transaction.',
  ],
  planning_effective_month: [
    '生效月份不能早于本月，且须晚于上一版配置及已核对月份。周期起始日不能晚于生效月份。',
    'Choose this month or later, after the latest configuration and reviewed occurrences. The schedule must start by that month.',
  ],
  planning_ended: ['此固定支出已结束。', 'This plan has ended.'],
  planning_period_limit: [
    '当月交易超过 10,000 笔，暂无法读取完整规划数据。',
    'This month exceeds the 10,000 transaction limit.',
  ],
  planning_currency: ['币种与账户不一致。', 'Currency must match the account.'],
  planning_conflict: ['操作标识冲突，请刷新核对。', 'Operation conflict. Refresh to review.'],
}
export function planningError(error: unknown, english: boolean): string {
  return apiErrorMessage(error, english, errors)
}

export function usePlanningMonth<T extends { month: string }>(
  load: (month: string) => Promise<T>,
  selectedMonth: string,
  english: boolean,
  visible = true,
  onSaved?: () => void,
  externalRevision = 0,
) {
  const month = selectedMonth.slice(0, 7)
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const active = useRef(false)
  const generation = useRef(0)
  const writing = useRef(false)

  const refresh = useCallback(
    async (afterSave = false) => {
      const token = ++generation.current
      setRefreshKey((value) => value + 1)
      setLoading(true)
      setError('')
      try {
        const result = await load(month)
        if (active.current && token === generation.current) setData(result)
      } catch (error) {
        if (active.current && token === generation.current) {
          setError(
            afterSave
              ? english
                ? 'Saved, but the updated list could not be loaded. Refresh to view it.'
                : '已保存，但最新列表读取失败，请刷新查看。'
              : planningError(error, english),
          )
        }
      } finally {
        if (active.current && token === generation.current) setLoading(false)
      }
    },
    [load, month, english],
  )

  useEffect(() => {
    active.current = true
    const requestGeneration = generation
    if (visible) void refresh()
    return () => {
      active.current = false
      requestGeneration.current++
    }
  }, [refresh, visible, externalRevision])

  async function perform<R>(
    action: () => Promise<R>,
    success?: string | ((result: R) => string),
  ): Promise<boolean> {
    if (writing.current) return false
    writing.current = true
    generation.current++
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await action()
      onSaved?.()
      if (!active.current) return false
      setNotice(
        typeof success === 'function'
          ? success(result)
          : (success ?? (english ? 'Saved' : '已保存')),
      )
      await refresh(true)
      return true
    } catch (error) {
      if (active.current) setError(planningError(error, english))
      return false
    } finally {
      writing.current = false
      if (active.current) {
        setBusy(false)
        setLoading(false)
      }
    }
  }
  return {
    month,
    data: data?.month.slice(0, 7) === month ? data : null,
    loading,
    busy,
    error,
    notice,
    refresh,
    refreshKey,
    perform,
  }
}

export type PlanningState<T extends { month: string }> = ReturnType<typeof usePlanningMonth<T>>
