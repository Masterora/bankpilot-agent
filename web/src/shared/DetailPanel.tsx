/** 文件职责：统一详情侧栏的模态、键盘关闭和焦点恢复；关闭原因由调用方处理。 */
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { IconButton } from './ui'

export function DetailPanel({
  open,
  title,
  closeLabel,
  onClose,
  children,
}: {
  open: boolean
  title: string
  closeLabel: string
  onClose: () => void
  children: ReactNode
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useId()
  useEffect(() => {
    const node = dialog.current
    if (open) node?.showModal()
    else node?.close()
    return () => node?.close()
  }, [open])
  return (
    <dialog
      ref={dialog}
      className="detail-panel"
      aria-labelledby={heading}
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
