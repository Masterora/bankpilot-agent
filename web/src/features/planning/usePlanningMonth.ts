/**
 * 文件职责：管理规划页面的月份读取与显式写操作。
 * 主要内容：加载和刷新、写入状态、失败提示及异步结果隔离。
 * 关键边界：迟到响应不能覆盖新月份，失败保留编辑上下文，具体 API 由调用方提供。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { planningError } from './errors'

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
