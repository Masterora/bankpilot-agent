/**
 * 文件职责：统一前端 API 错误展示。
 * 主要内容：按稳定业务码查找文案，处理通用 HTTP 状态及未知失败。
 * 关键边界：业务模块提供专属提示；不将内部异常详情直接展示给用户。
 */
import { ApiError } from '../api'

export type ErrorMessages = Record<string, readonly [string, string]>
const common: ErrorMessages = {
  invalid_response: [
    '服务响应异常，请稍后刷新核对结果。',
    'Unexpected response. Refresh to check the result.',
  ],
}
const statuses: Record<number, readonly [string, string]> = {
  401: ['登录已过期，请重新登录。', 'Session expired. Sign in again.'],
  403: ['没有执行此操作的权限。', 'You do not have permission for this action.'],
  413: [
    '文件超过处理上限，请缩小文件后重试。',
    'The file exceeds the processing limit. Use a smaller file.',
  ],
  422: ['请检查填写的日期、金额及其他字段。', 'Check the dates, amounts and other input values.'],
  429: ['请求过于频繁，请稍后重试。', 'Too many requests. Please retry later.'],
  503: [
    '服务暂不可用，请稍后重试；提交过的操作请先核对结果。',
    'Service unavailable. Retry later; check submitted changes first.',
  ],
  504: ['处理超时，请核对结果后重试。', 'Request timed out. Check the result before retrying.'],
}
export function apiErrorMessage(
  error: unknown,
  english: boolean,
  messages: ErrorMessages = {},
): string {
  if (error instanceof ApiError) {
    const message = messages[error.code] ?? common[error.code] ?? statuses[error.status]
    if (message) return message[english ? 1 : 0]
  }
  return english
    ? 'Request incomplete. Check the result before retrying.'
    : '请求未完成，请核对结果后重试。'
}
