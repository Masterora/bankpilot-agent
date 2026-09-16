/** 文件职责：保存当前标签页的一次待确认导入；不存文件内容或凭据。 */
import type { ImportStatementPayload } from '../../types'

export const IMPORT_RECOVERY_KEY = 'bankpilot.import.pending'

export interface PendingImport {
  user_id: string
  key: string
  content_digest: string
  request_digest: string
  config: Omit<ImportStatementPayload, 'content'>
}

export function readPendingImport(userId: string): PendingImport | null {
  const raw = sessionStorage.getItem(IMPORT_RECOVERY_KEY)
  if (!raw) return null
  const value = JSON.parse(raw) as PendingImport
  if (value.user_id !== userId) {
    sessionStorage.removeItem(IMPORT_RECOVERY_KEY)
    return null
  }
  if (!value.key || !value.content_digest || !value.request_digest
    || !value.config?.mapping || !value.config.file_name) {
    throw new Error('导入恢复信息无效，请核对导入历史')
  }
  return value
}

export function savePendingImport(value: PendingImport) {
  sessionStorage.setItem(IMPORT_RECOVERY_KEY, JSON.stringify(value))
}

export function clearPendingImport() {
  sessionStorage.removeItem(IMPORT_RECOVERY_KEY)
}
