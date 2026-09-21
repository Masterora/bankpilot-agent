/**
 * 文件职责：管理账本搜索请求与结果有效性。
 * 主要内容：查询和分页状态、错误保留、请求序号，以及账本变化、退出和停用后的失效处理。
 * 关键边界：迟到响应不能覆盖新查询；跨页携带账本与搜索版本，失效结果须显式重新查询。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { SearchFilters, SearchPage } from './search'
import { versions } from './search'

export function useTransactionSearch(active: boolean) {
  const [page, setPage] = useState<SearchPage | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [stale, setStale] = useState(false)
  const epoch = useRef(0)
  const query = useCallback(async (filters: SearchFilters, offset = 0, previous?: SearchPage) => {
    const version = ++epoch.current
    setBusy(true); setError(null)
    try {
      const result = await api.search(filters, offset, previous ? versions(previous) : undefined)
      if (version !== epoch.current) return
      setPage(result); setStale(false)
      return result
    } catch (cause) { if (version === epoch.current) { setError(cause); setStale(true) } }
    finally { if (version === epoch.current) setBusy(false) }
  }, [])
  useEffect(() => {
    const invalidate = () => { epoch.current++; setStale(true); setBusy(false) }
    window.addEventListener('bankpilot:ledger-changed', invalidate)
    window.addEventListener('bankpilot-logout', invalidate)
    return () => { invalidate(); window.removeEventListener('bankpilot:ledger-changed', invalidate); window.removeEventListener('bankpilot-logout', invalidate) }
  }, [])
  useEffect(() => { if (!active) { epoch.current++; setBusy(false) } }, [active])
  return { page, busy, error, stale, query }
}
