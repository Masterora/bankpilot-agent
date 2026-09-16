/**
 * 文件职责：管理月报请求、任务轮询与用户操作。
 * 主要内容：提交幂等、历史选择、刷新、删除及导出状态。
 * 关键边界：仅待完成任务轮询；失败保留上下文，迟到响应不能覆盖当前选择。
 */
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { downloadFile } from '../../shared/download'
import { newIdempotencyKey } from '../../shared/operationKey'
import type { MonthlyReport, ReportDetail } from '../../types'

function errorMessage(error: unknown, english: boolean): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return english ? 'Two reports are already pending. Try again when one finishes.' : '已有两份报告待完成，请稍后重试。'
    if (error.status === 404 || error.status === 410) return english ? 'This report is no longer available. Refresh the list.' : '报告已不可用，请刷新列表。'
    if (error.status === 401) return english ? 'Your session expired. Sign in again.' : '登录已过期，请重新登录。'
  }
  return english ? 'Request failed. Your input and results have been kept. Please retry.' : '请求失败，已保留输入和结果，请重试。'
}

export function useReports(initialMonth: string, english: boolean) {
  const [month, setMonth] = useState(initialMonth.slice(0, 7))
  const [items, setItems] = useState<MonthlyReport[]>([])
  const [offset, setOffset] = useState(0)
  const [displayedOffset, setDisplayedOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [listError, setListError] = useState(false)
  const [detailError, setDetailError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submission = useRef<{ month: string; key: string } | null>(null)
  const mutation = useRef(false)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    function revalidate() {
      if (document.visibilityState === 'visible') setRefresh((value) => value + 1)
    }
    document.addEventListener('visibilitychange', revalidate)
    window.addEventListener('focus', revalidate)
    return () => {
      document.removeEventListener('visibilitychange', revalidate)
      window.removeEventListener('focus', revalidate)
    }
  }, [])

  useEffect(() => {
    let active = true
    let timer: number | undefined
    async function load() {
      if (document.visibilityState === 'hidden') return
      try {
        const result = await api.reports(offset)
        if (!active) return
        setItems(result.items)
        setDisplayedOffset(offset)
        setHasMore(result.has_more)
        setListError(false)
        if (result.items.some((item) => item.status === 'QUEUED' || item.status === 'RUNNING')) {
          timer = window.setTimeout(() => { void load() }, 3000)
        }
      } catch {
        if (active) setListError(true)
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }
    void load()
    return () => { active = false; window.clearTimeout(timer) }
  }, [offset, refresh])

  useEffect(() => {
    if (!selected) return
    let active = true
    let timer: number | undefined
    async function load() {
      if (document.visibilityState === 'hidden') return
      try {
        const status = await api.reportStatus(selected!)
        if (!active) return
        const pending = status.status === 'QUEUED' || status.status === 'RUNNING'
        const result = pending ? { ...status, snapshot: null } : await api.report(selected!)
        if (!active) return
        setDetail(result)
        setDetailError(false)
        if (pending) timer = window.setTimeout(() => { void load() }, 3000)
      } catch {
        if (active) setDetailError(true)
      }
    }
    void load()
    return () => { active = false; window.clearTimeout(timer) }
  }, [selected, refresh])

  function selectReport(id: string) {
    if (id === selected) return
    setSelected(id)
    setDetail(null)
    setDetailError(false)
  }

  async function generate(targetMonth: string) {
    if (mutation.current) return
    mutation.current = true
    setBusy(true)
    setError('')
    if (submission.current?.month !== targetMonth) submission.current = { month: targetMonth, key: newIdempotencyKey() }
    try {
      const result = await api.createReport(`${targetMonth}-01`, submission.current.key)
      if (!mounted.current) return
      submission.current = null
      setOffset(0)
      selectReport(result.id)
      setRefresh((value) => value + 1)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 410) submission.current = null
      if (mounted.current) setError(errorMessage(cause, english))
    } finally {
      mutation.current = false
      if (mounted.current) setBusy(false)
    }
  }

  async function remove(id: string) {
    if (mutation.current) return
    mutation.current = true
    setBusy(true)
    setError('')
    try {
      await api.deleteReport(id)
      if (!mounted.current) return
      setSelected((current) => current === id ? null : current)
      setDetail((current) => current?.id === id ? null : current)
      setOffset(0)
      setRefresh((value) => value + 1)
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause, english))
    } finally {
      mutation.current = false
      if (mounted.current) setBusy(false)
    }
  }

  async function exportReport(id: string) {
    try {
      const content = await api.exportReport(id)
      if (mounted.current) downloadFile(JSON.stringify(content, null, 2), `bankpilot-report-${id}.json`, 'application/json')
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause, english))
    }
  }

  return {
    month, setMonth, items, offset: displayedOffset, hasMore, selected, detail,
    goToPage: (nextOffset: number) => {
      setOffset(nextOffset)
      setLoading(true)
      setRefresh((value) => value + 1)
    },
    listError, detailError, loading, busy, error,
    selectReport, generate, remove, exportReport,
    refreshReports: () => setRefresh((value) => value + 1),
  }
}
