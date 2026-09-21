/**
 * 文件职责：在存在未保存输入时处理浏览器离开提示。
 * 主要内容：按脏状态注册并清理 beforeunload 监听。
 * 关键边界：仅覆盖刷新和关闭；站内导航和草稿保留由调用页面负责。
 */
import { useEffect } from 'react'
export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
}
