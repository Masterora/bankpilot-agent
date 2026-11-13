/** Page identity is metadata, never a credential; the server compares it with the Cookie. */
import { newIdempotencyKey } from './operationKey'
let identity: string | null = null
export const sessionChangeKey = 'bankpilot.auth-change'

export function sessionIdentity() {
  return identity
}
export function bindSessionIdentity(value: string | null) {
  identity = value
}
export function announceSessionChange() {
  try {
    localStorage.setItem(sessionChangeKey, newIdempotencyKey())
  } catch {
    /* server still guards */
  }
}
export function invalidateSession() {
  identity = null
  window.dispatchEvent(new Event('bankpilot:session-invalidated'))
}
