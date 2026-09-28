/** Tab-local frozen requests; no amounts, account data or credentials are persisted. */
import type { AttentionStateRequest, AttentionType } from './attention'

export const ATTENTION_RECOVERY_KEY = 'bankpilot.attention.pending'
export type PendingAttention = { user_id: string } & (
  | { kind: 'state'; payload: AttentionStateRequest }
  | { kind: 'preference'; type: AttentionType; payload: {
    operation_id: string; enabled: boolean; expected_version: number
  } }
)

export function readPendingAttention(userId: string): PendingAttention | null {
  const raw = sessionStorage.getItem(ATTENTION_RECOVERY_KEY)
  if (!raw) return null
  const value = JSON.parse(raw) as PendingAttention
  if (value.user_id !== userId) {
    sessionStorage.removeItem(ATTENTION_RECOVERY_KEY)
    return null
  }
  if (!value.payload?.operation_id || !['state', 'preference'].includes(value.kind)
    || (value.kind === 'state' && (!value.payload.source_id || !value.payload.source_date
      || !value.payload.fact_token || !value.payload.expected_state_version
      || !['budget', 'recurring'].includes(value.payload.source_type)
      || !['read', 'snooze', 'restore'].includes(value.payload.action)))
    || (value.kind === 'preference' && (!value.type || typeof value.payload.enabled !== 'boolean'
      || !Number.isInteger(value.payload.expected_version)))) {
    throw new Error('Invalid attention recovery record')
  }
  return value
}

export function savePendingAttention(value: PendingAttention) {
  sessionStorage.setItem(ATTENTION_RECOVERY_KEY, JSON.stringify(value))
}

export function clearPendingAttention(operationId?: string) {
  if (operationId) {
    const raw = sessionStorage.getItem(ATTENTION_RECOVERY_KEY)
    if (!raw || (JSON.parse(raw) as PendingAttention).payload.operation_id !== operationId) return
  }
  sessionStorage.removeItem(ATTENTION_RECOVERY_KEY)
}
