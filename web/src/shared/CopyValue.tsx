/**
 * 文件职责：展示可选择的完整标识，并提供有明确结果反馈的复制操作。
 * 关键边界：只在用户点击时访问剪贴板；失败保留原文供手动选择，不使用回退复制。
 */
import { useState } from 'react'

export function CopyValue({ value, english }: { value: string; english: boolean }) {
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle')
  async function copy() {
    if (state === 'busy') return
    setState('busy')
    try { await navigator.clipboard.writeText(value); setState('done') }
    catch { setState('failed') }
  }
  return <><span className="copy-value"><code>{value}</code><button type="button" disabled={state === 'busy'} aria-busy={state === 'busy'} onClick={() => void copy()}>{english ? 'Copy' : '复制'}</button></span>
    <span className="copy-feedback" role="status">{state === 'done' ? (english ? 'Copied' : '已复制') : state === 'failed' ? (english ? 'Select the text to copy manually.' : '请选中文字手动复制。') : ''}</span></>
}
