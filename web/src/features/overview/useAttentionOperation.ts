/** One authoritative operation state, mirrored synchronously for rapid event handlers. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { apiErrorMessage } from '../../shared/apiErrors'
import { clearPendingAttention, readPendingAttention, savePendingAttention } from './attentionRecovery'
import type { PendingAttention } from './attentionRecovery'

type OperationState =
  | { phase: 'idle'; error?: string }
  | { phase: 'blocked'; error: string }
  | { phase: 'unconfirmed'; request: PendingAttention; error: string }
  | { phase: 'submitting'; request: PendingAttention }

export function useAttentionOperation(userId: string, english: boolean) {
  const [state, setState] = useState<OperationState>({ phase: 'idle' })
  const current = useRef(state)
  const alive = useRef(true)
  const transition = useCallback((next: OperationState) => {
    current.current = next
    if (alive.current) setState(next)
  }, [])
  const recover = useCallback(() => {
    if (current.current.phase === 'submitting') return
    try {
      const request = readPendingAttention(userId)
      transition(request ? { phase: 'unconfirmed', request, error: english
        ? 'An operation is unconfirmed. Retry the original operation.'
        : '存在未确认操作，请使用原操作重试。' } : { phase: 'idle' })
    } catch {
      transition({ phase: 'blocked', error: english
        ? 'Recovery storage is unavailable. Restore browser storage and retry recovery.'
        : '无法读取操作恢复信息，已暂停写入。请恢复浏览器存储后重试恢复。' })
    }
  }, [userId, english, transition])
  useEffect(() => {
    alive.current = true
    const logout = () => { alive.current = false }
    window.addEventListener('bankpilot-logout', logout)
    recover()
    return () => { alive.current = false; window.removeEventListener('bankpilot-logout', logout) }
  }, [recover])

  async function submit(request?: PendingAttention): Promise<boolean> {
    if (!alive.current || current.current.phase === 'submitting' || current.current.phase === 'blocked') return false
    if (current.current.phase === 'unconfirmed') {
      if (request) return false
      request = current.current.request
    }
    if (!request) return false
    try { savePendingAttention(request) }
    catch {
      // Re-read on recovery; never discard a previous unconfirmed operation.
      transition({ phase: 'blocked', error: english
        ? 'Recovery could not be saved. Nothing was sent; restore browser storage and retry recovery.'
        : '无法保存操作恢复信息，尚未发送。请恢复浏览器存储后重试恢复。' })
      return false
    }
    transition({ phase: 'submitting', request })
    try {
      if (request.kind === 'state') await api.attentionState(request.payload)
      else await api.attentionPreference(request.type, request.payload)
      clearPendingAttention(request.payload.operation_id)
      transition({ phase: 'idle' })
      return true
    } catch (cause) {
      const rejected = cause instanceof ApiError && [400, 404, 409, 422].includes(cause.status)
      if (rejected) {
        try {
          clearPendingAttention(request.payload.operation_id)
          transition({ phase: 'idle', error: apiErrorMessage(cause, english, {
            attention_unavailable: ['该月份超过待办计算上限，请先核对导入范围；刷新不能解除容量限制。', 'This month exceeds the attention capacity. Review the imported range; refreshing cannot resolve it.'],
            attention_stale: ['待办已经变化，请重新读取后操作。', 'This item changed. Reload before trying again.'],
            attention_state_conflict: ['处理状态已变化，请重新读取。', 'The handling state changed. Reload the list.'],
            attention_preference_conflict: ['提醒设置已变化，请重新读取。', 'Reminder settings changed. Reload the list.'],
          }) })
          return false
        } catch { /* Keep the frozen request until durable cleanup succeeds. */ }
      }
      transition({ phase: 'unconfirmed', request, error: english
        ? 'The result is unknown. Retry the original operation.'
        : '操作结果未确认，可使用原操作重试。' })
      return false
    }
  }
  return { state, submit, recover, locked: state.phase !== 'idle',
    error: 'error' in state ? state.error : '' }
}
