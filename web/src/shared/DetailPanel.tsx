/**
 * 文件职责：提供共享的模态详情侧栏。
 * 主要内容：侧栏展示、键盘关闭、焦点约束与关闭后焦点恢复。
 * 关键边界：关闭行为通知调用方，不自行处理业务保存或丢弃草稿。
 */
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { IconButton } from './ui'

export function DetailPanel({
  open,
  title,
  closeLabel,
  onClose,
  children,
  docked = false,
}: {
  open: boolean
  title: string
  closeLabel: string
  onClose: () => void
  children: ReactNode
  docked?: boolean
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useId()
  useEffect(() => {
    const node = dialog.current
    if (!node) return
    const previousFocus = document.activeElement
    const wide = window.matchMedia('(min-width: 1280px)')
    const panel = node
    function sync() {
      panel.close()
      if (open) {
        if (docked && wide.matches) panel.show()
        else panel.showModal()
      }
    }
    sync()
    if (docked) wide.addEventListener('change', sync)
    return () => {
      if (docked) wide.removeEventListener('change', sync)
      node.close()
      if (open && previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [open, docked])
  return (
    <dialog
      ref={dialog}
      className={`detail-panel${docked ? ' assistant-panel' : ''}`}
      aria-labelledby={heading}
      onKeyDown={(event) => {
        if (docked && event.key === 'Escape') { event.preventDefault(); onClose() }
      }}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
    >
      <header>
        <h2 id={heading}>{title}</h2>
        <IconButton icon="close" label={closeLabel} onClick={onClose} />
      </header>
      <div className="detail-panel-body">{children}</div>
    </dialog>
  )
}
