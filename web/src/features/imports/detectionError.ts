/**
 * 文件职责：将账单识别失败转换为可操作的用户提示。
 * 主要内容：区分服务版本、认证、文件校验、限流与网络故障，并决定是否允许原文件重试。
 * 关键边界：不展示服务端原始异常，不把网络或部署问题归因于账单格式。
 */
import { ApiError } from '../../api'

export function detectionError(reason: unknown, english: boolean): { message: string; retry: boolean } {
  const status = reason instanceof ApiError ? reason.status : 0
  const messages: Record<number, [string, string]> = {
    401: ['登录已失效，请重新登录后选择账单。', 'Your session expired. Sign in and select the statement again.'],
    403: ['无权识别账单，请确认登录账户与访问权限。', 'Access denied. Check your account and permissions.'],
    404: ['账单识别服务尚未就绪，请更新 API 后重试，无需修改文件。', 'Statement detection is unavailable. Update the API and retry without changing the file.'],
    413: ['账单超过服务大小限制，请保留原文件并选择较小期间的导出账单。', 'The statement exceeds the service size limit. Export a shorter period.'],
    422: ['账单结构或账户信息未通过识别，请保留原文件并核对支持范围。', 'The statement structure or account details could not be recognized. Keep the original and check supported formats.'],
    429: ['识别请求过于频繁，请稍后重试。', 'Too many detection requests. Retry later.'],
  }
  const fallback = ['账单识别请求失败，请检查网络或服务后重试，无需修改文件。', 'Statement detection failed. Check the network or service and retry without changing the file.']
  return { message: (messages[status] ?? fallback)[english ? 1 : 0], retry: ![401, 403, 413, 422].includes(status) }
}
