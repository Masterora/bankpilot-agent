/**
 * 文件职责：管理工作区可恢复的 URL 导航状态。
 * 主要内容：页面与期间解析、历史记录写入、浏览器前进后退订阅。
 * 关键边界：URL 仅保存页面和日期，不保存文件、凭据或账单内容。
 */
import { useEffect, useState } from 'react'
import { pageDefinitions } from './pages'
import type { ProductPage } from './pages'
import { currentPeriod, validPeriod } from '../shared/period'
import type { ReviewPeriod } from '../shared/period'

function readRoute() {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const page = pageDefinitions.find((item) => item.id === params.get('page'))?.id ?? 'overview'
  const period = { start: params.get('start') ?? '', end: params.get('end') ?? '' }
  return { page, period: validPeriod(period) ? period : currentPeriod() }
}

export function useWorkspaceRoute() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const restore = () => setRoute(readRoute())
    if (!window.location.hash) {
      const initial = readRoute()
      window.history.replaceState(null, '', `#${new URLSearchParams({ page: initial.page, ...initial.period })}`)
    }
    window.addEventListener('popstate', restore)
    window.addEventListener('hashchange', restore)
    return () => {
      window.removeEventListener('popstate', restore)
      window.removeEventListener('hashchange', restore)
    }
  }, [])
  function update(page: ProductPage, period: ReviewPeriod) {
    setRoute({ page, period })
    if (!validPeriod(period)) return
    const hash = `#${new URLSearchParams({ page, ...period })}`
    if (window.location.hash !== hash) window.history.pushState(null, '', hash)
  }
  return {
    activePage: route.page,
    reviewPeriod: route.period,
    setActivePage: (page: ProductPage) => update(page, route.period),
    setReviewPeriod: (period: ReviewPeriod) => update(route.page, period),
  }
}
