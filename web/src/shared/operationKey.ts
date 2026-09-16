/** 文件职责：为显式写操作生成随机 UUID，不在重试时更换身份。 */
export function newIdempotencyKey(): string {
  // 私网 HTTP 页面也可使用 getRandomValues，不依赖仅安全上下文提供的 randomUUID。
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
