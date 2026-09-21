/**
 * 文件职责：管理工作区可恢复的 URL 导航状态。
 * 主要内容：页面与期间解析、历史记录写入、浏览器前进后退订阅。
 * 关键边界：URL hash 保存页面、日期与已提交查找条件，不保存凭据或文件；退出时清理。
 */
import { useEffect, useState } from 'react'
import { pageDefinitions } from './pages'
import type { ProductPage } from './pages'
import { currentPeriod, validPeriod, monthPeriod } from '../shared/period'
import type { ReviewPeriod } from '../shared/period'

function readRoute() {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const page = pageDefinitions.find((item) => item.id === params.get('page'))?.id ?? 'overview'
  const period = { start: params.get('start') ?? '', end: params.get('end') ?? '' }
  const selectedPeriod = validPeriod(period) ? period : currentPeriod()
  const selectedMonth = (key: string) => {
    const value = params.get(key) ?? selectedPeriod.start.slice(0, 7)
    return monthPeriod(value) ? value : currentPeriod().start.slice(0, 7)
  }
  const overview = {
    start: params.get('overviewStart') ?? selectedPeriod.start,
    end: params.get('overviewEnd') ?? selectedPeriod.end,
  }
  return {
    page,
    overviewPeriod: validPeriod(overview) ? overview : currentPeriod(),
    period: selectedPeriod,
    budgetMonth: selectedMonth('budgetMonth'),
    recurringMonth: selectedMonth('recurringMonth'),
  }
}

export function useWorkspaceRoute(locked = { budgets: false, recurring: false }) {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const restore = () => {
      const next = readRoute()
      // History may change pages, but must not replace the month owning an unsaved form.
      if (locked.budgets) next.budgetMonth = route.budgetMonth
      if (locked.recurring) next.recurringMonth = route.recurringMonth
      window.history.replaceState(
        null,
        '',
        `#${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(window.location.hash.slice(1))), page: next.page, ...next.period, overviewStart: next.overviewPeriod.start, overviewEnd: next.overviewPeriod.end, budgetMonth: next.budgetMonth, recurringMonth: next.recurringMonth })}`,
      )
      setRoute(next)
    }
    if (!window.location.hash) {
      const initial = readRoute()
      window.history.replaceState(
        null,
        '',
        `#${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(window.location.hash.slice(1))), page: initial.page, ...initial.period, overviewStart: initial.overviewPeriod.start, overviewEnd: initial.overviewPeriod.end, budgetMonth: initial.budgetMonth, recurringMonth: initial.recurringMonth })}`,
      )
    }
    window.addEventListener('popstate', restore)
    window.addEventListener('hashchange', restore)
    return () => {
      window.removeEventListener('popstate', restore)
      window.removeEventListener('hashchange', restore)
    }
  }, [locked.budgets, locked.recurring, route.budgetMonth, route.recurringMonth])
  function update(
    page: ProductPage,
    period: ReviewPeriod,
    month?: string,
    overviewPeriod = route.overviewPeriod,
  ) {
    const budgetMonth = page === 'budgets' && month ? month : route.budgetMonth
    const recurringMonth = page === 'recurring' && month ? month : route.recurringMonth
    setRoute({ page, period, overviewPeriod, budgetMonth, recurringMonth })
    if (!validPeriod(period)) return
    const hash = `#${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(window.location.hash.slice(1))), page, ...period, overviewStart: overviewPeriod.start, overviewEnd: overviewPeriod.end, budgetMonth, recurringMonth })}`
    if (window.location.hash !== hash) window.history.pushState(null, '', hash)
  }
  return {
    activePage: route.page,
    budgetMonth: route.budgetMonth,
    recurringMonth: route.recurringMonth,
    setPlanningMonth: (month: string) => {
      if (monthPeriod(month)) update(route.page, route.period, month)
    },
    navigateTo: (page: ProductPage, month?: string, period = route.period) =>
      update(page, period, month),
    overviewPeriod: route.overviewPeriod,
    setOverviewPeriod: (period: ReviewPeriod) =>
      update(route.page, route.period, undefined, period),
    reviewPeriod: route.period,
    setActivePage: (page: ProductPage) => update(page, route.period),
    setReviewPeriod: (period: ReviewPeriod) => update(route.page, period),
  }
}
