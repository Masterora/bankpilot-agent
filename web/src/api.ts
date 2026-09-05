/**
 * 文件职责：封装 BankPilot Web 访问 v1 API 的同源 HTTP 请求。
 *
 * 主要内容：
 * - `ApiError`：保留 HTTP 状态码和服务端错误信息。
 * - `request`：统一注入 Cookie 凭证、JSON 请求头和错误处理。
 * - `api`：提供注册、认证、卡片、账单导入、运行、SSE 与分类修正方法。
 *
 * 关键边界：会话由浏览器 Cookie 自动携带，本文件不保存密码或令牌。
 */

import type {
  ImportBatch,
  ImportBatchList,
  ImportStatementPayload,
  Run,
  RunEvent,
  TransactionCategory,
  User,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 凭证由浏览器管理，避免应用 JavaScript 读取会话令牌。
  const response = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(body?.detail ?? '请求失败', response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  reviews: (start: string, end: string) => request<{ summaries: import('./types').CurrencySummary[]; items: import('./types').ReviewItem[] }>(`/api/v1/reviews?start_date=${start}&end_date=${end}`),
  saveReview: (start: string, end: string, key: string, state: import('./types').ReviewItem['state'], note: string) => request<void>('/api/v1/reviews', { method: 'POST', body: JSON.stringify({ start_date: start, end_date: end, key, state, note }) }),
  runHistory: () => request<{ items: { id: string; message: string; status: string; created_at: string }[] }>('/api/v1/run-history'),
  register: (email: string, password: string) =>
    request<User>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<User>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>('/api/v1/auth/me'),
  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),
  listAccounts: () => request<{ items: { id: string; name: string; currency: string }[] }>('/api/v1/accounts'),
  ledger: (start: string, end: string) => request<import('./types').RunResult['transactions']>(`/api/v1/transactions?start_date=${start}&end_date=${end}`),
  correctLedgerCategory: (id: string, category: TransactionCategory) => request<void>(`/api/v1/transactions/${id}/category`, { method: 'POST', body: JSON.stringify({ category }) }),
  listImports: () => request<ImportBatchList>('/api/v1/imports'),
  detectImport: (content: string) => request<{ mapping: import('./types').ImportFieldMapping; account_name: string | null; currency: string | null }>('/api/v1/imports/detect', { method: 'POST', body: JSON.stringify({ content }) }),
  revokeImport: (id: string) => request<void>(`/api/v1/imports/${id}/revoke`, { method: 'POST' }),
  previewImport: (payload: ImportStatementPayload) => request<{ total_rows: number; error_rows: number; duplicate_rows: number; errors: { row_number: number; message: string }[]; rows: { row_number: number; date: string; merchant: string; amount: string }[] }>('/api/v1/imports/preview', { method: 'POST', body: JSON.stringify(payload) }),
  importStatement: (payload: ImportStatementPayload) =>
    request<ImportBatch>('/api/v1/imports', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createRun: (message: string) =>
    request<Run>('/api/v1/runs', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
  getRun: (runId: string) => request<Run>(`/api/v1/runs/${runId}`),
  correctCategory: (runId: string, transactionId: string, category: TransactionCategory) =>
    request<Run>(`/api/v1/runs/${runId}/transactions/${transactionId}/category`, {
      method: 'POST',
      body: JSON.stringify({ category }),
    }),
  watchRunEvents: (
    runId: string,
    onEvent: (event: RunEvent) => void,
    onError: () => void,
  ) => {
    // EventSource 自动携带同源 Cookie，并使用 Last-Event-ID 恢复断开的事件流。
    const source = new EventSource(`/api/v1/runs/${runId}/events`)
    source.onmessage = (message) => onEvent(JSON.parse(message.data) as RunEvent)
    source.onerror = onError
    return source
  },
}
