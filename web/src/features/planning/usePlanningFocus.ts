/** 将总览待办跳转定位到规划卡片。
 * 只改变视图焦点，不修改业务数据或表单输入。
 */
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
