/**
 * 文件职责：保存当前标签页待确认导入的恢复信息。
 * 主要内容：读写和清理 sessionStorage 中的用户身份、幂等键、摘要与导入配置。
 * 关键边界：不保存文件正文或凭据；不同用户的记录清除，无效记录显式报错。
 */
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
