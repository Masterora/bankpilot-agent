/** 文件职责：从总览进入具体待办后定位卡片，不改变数据和表单。 */
import { useEffect } from 'react'
export function usePlanningFocus(target: string, loading: boolean, active: boolean) {
  useEffect(() => {
    if (!target || loading || !active) return
    const element = document.getElementById(target)
    element?.scrollIntoView({
      block: 'center',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
    })
    element?.focus({ preventScroll: true })
  }, [target, loading, active])
}
