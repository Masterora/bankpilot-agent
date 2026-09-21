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
  Account,
  CurrencySummary,
  ImportFieldMapping,
  ImportPreview,
  MonthlyReport,
  OverviewSnapshot,
  RelationKind,
  RelationWorkspace,
  ReportDetail,
  ReviewItem,
  RunResult,
  ImportBatch,
  ImportBatchList,
  ImportStatementPayload,
  Run,
  RunEvent,
  TransactionCategory,
  User,
} from './types'

import type { AssistantAction, ChatMessage, Reply, SpendingPage, SpendingScope, SpendingSummary } from './features/assistant/types'

import type { BudgetInput, BudgetWorkspace, RecurringEditInput, RecurringInput, RecurringItem, RecurringTransaction, RecurringWorkspace } from './features/planning/types'

import type { Locale } from './i18n'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 凭证由浏览器管理，避免应用 JavaScript 读取会话令牌。
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = body.detail
      if (
        typeof detail === 'object' && detail !== null &&
        'code' in detail && typeof detail.code === 'string' &&
        'message' in detail && typeof detail.message === 'string'
      ) {
        throw new ApiError(detail.message, response.status, detail.code)
      }
    }
    throw new ApiError('服务响应格式无效', response.status, 'invalid_response')
  }
  if (init?.method === 'POST' && /^\/api\/v1\/(?:imports(?:\/[^/]+\/revoke)?|relations|accounts\/[^/]+\/name|transactions\/[^/]+\/category|runs\/[^/]+\/transactions\/[^/]+\/category)$/.test(path)) {
    window.dispatchEvent(new Event('bankpilot:ledger-changed'))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  assistantChat: (messages: ChatMessage[], month: string, locale: Locale, spending_context: SpendingScope | null = null) => request<Reply>('/api/v1/assistant/chat', { method: 'POST', body: JSON.stringify({ messages, month: `${month.slice(0, 7)}-01`, locale, spending_context }) }),
  spendingEvidence: (summary: SpendingSummary, page: number) => {
    const params = new URLSearchParams({ ...summary.scope, expected_revision: String(summary.ledger_revision), expected_calculation_version: summary.calculation_version, page: String(page) })
    return request<SpendingPage>(`/api/v1/assistant/spending-evidence?${params}`)
  },
  assistantAction: (id: string, cancel: boolean) => request<AssistantAction>(`/api/v1/assistant/${cancel ? 'cancel' : 'confirm'}`, { method: 'POST', body: JSON.stringify({ id }) }),
  budgets: (month: string) => request<BudgetWorkspace>(`/api/v1/budgets?month=${month}-01`),
  saveBudget: (payload: BudgetInput) => request<void>('/api/v1/budgets', { method: 'POST', body: JSON.stringify(payload) }),
  deleteBudget: (payload: Omit<BudgetInput, 'amount'>) => request<void>('/api/v1/budgets/delete', { method: 'POST', body: JSON.stringify(payload) }),
  copyBudgets: (month: string) => request<{ copied: number; source_count: number }>('/api/v1/budgets/copy', { method: 'POST', body: JSON.stringify({ month: `${month}-01` }) }),
  recurring: (month: string) => request<RecurringWorkspace>(`/api/v1/recurring?month=${month}-01`),
  recurringCandidates: (month: string) => request<RecurringTransaction[]>(`/api/v1/recurring/candidates?month=${month}-01`),
  createRecurring: (payload: RecurringInput) => request<void>('/api/v1/recurring', { method: 'POST', body: JSON.stringify(payload) }),
  editRecurring: (payload: RecurringEditInput) => request<void>(`/api/v1/recurring/${payload.id}/edit`, { method: 'POST', body: JSON.stringify(payload) }),
  recurringDraft: (id: string) => request<RecurringInput>(`/api/v1/recurring/draft?transaction_id=${id}`),
  skipRecurring: (id: string, due_date: string, skipped: boolean, expected_version: number) => request<void>(`/api/v1/recurring/${id}/skip`, { method: 'POST', body: JSON.stringify({ due_date, skipped, expected_version }) }),
  cancelRecurringRevision: (id: string, effective_month: string, expected_version: number) => request<void>(`/api/v1/recurring/${id}/cancel-revision`, { method: 'POST', body: JSON.stringify({ effective_month, expected_version }) }),
  recurringStatus: (id: string, status: RecurringItem['status'], expected_version: number) => request<void>(`/api/v1/recurring/${id}/status`, { method: 'POST', body: JSON.stringify({ status, expected_version }) }),
  matchRecurring: (id: string, due_date: string, transaction_id: string | null, expected_version: number) => request<void>(`/api/v1/recurring/${id}/match`, { method: 'POST', body: JSON.stringify({ due_date, transaction_id, expected_version }) }),
  overview: (start: string, end: string) => request<OverviewSnapshot>(`/api/v1/overview?start_date=${start}&end_date=${end}`),
  reports: (offset = 0) => request<{ items: MonthlyReport[]; has_more: boolean }>(`/api/v1/reports?offset=${offset}&limit=20`),
  report: (id: string) => request<ReportDetail>(`/api/v1/reports/${id}`),
  reportStatus: (id: string) => request<MonthlyReport>(`/api/v1/reports/${id}/status`),
  createReport: (month: string, idempotency_key: string) => request<MonthlyReport>('/api/v1/reports', { method: 'POST', body: JSON.stringify({ month, idempotency_key }) }),
  deleteReport: (id: string) => request<void>(`/api/v1/reports/${id}/delete`, { method: 'POST' }),
  exportReport: (id: string) => request<unknown>(`/api/v1/reports/${id}/export`),
  relations: (start: string, end: string) => request<RelationWorkspace>(`/api/v1/relations?start_date=${start}&end_date=${end}`),
  saveRelation: (payload: { kind: RelationKind; first_id: string; second_id: string; state: 'confirmed' | 'rejected' | 'revoked'; expected_version: number }) => request<void>('/api/v1/relations', { method: 'POST', body: JSON.stringify(payload) }),
  renameAccount: (id: string, name: string) => request<void>(`/api/v1/accounts/${id}/name`, { method: 'POST', body: JSON.stringify({ name }) }),
  decodeImport: (file_name: string, data: string) => request<{content: string; content_digest: string}>('/api/v1/imports/decode', {method: 'POST', body: JSON.stringify({file_name, data})}),
  reviews: (start: string, end: string) => request<{ summaries: CurrencySummary[]; items: ReviewItem[] }>(`/api/v1/reviews?start_date=${start}&end_date=${end}`),
  saveReview: (start: string, end: string, key: string, state: ReviewItem['state'], note: string) => request<void>('/api/v1/reviews', { method: 'POST', body: JSON.stringify({ start_date: start, end_date: end, key, state, note }) }),
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
  listAccounts: () => request<{ items: Account[] }>('/api/v1/accounts'),
  ledger: (start: string, end: string) => request<RunResult['transactions']>(`/api/v1/transactions?start_date=${start}&end_date=${end}`),
  correctLedgerCategory: (id: string, category: TransactionCategory) => request<void>(`/api/v1/transactions/${id}/category`, { method: 'POST', body: JSON.stringify({ category }) }),
  listImports: () => request<ImportBatchList>('/api/v1/imports'),
  detectImport: (content: string) => request<{ source: string; headers: string[]; mapping: ImportFieldMapping; account_name: string | null; currency: string | null }>('/api/v1/imports/detect', { method: 'POST', body: JSON.stringify({ content }) }),
  revokeImport: (id: string) => request<void>(`/api/v1/imports/${id}/revoke`, { method: 'POST' }),
  importByKey: (key: string) => request<ImportBatch>(`/api/v1/imports/by-key/${key}`),
  previewImport: (payload: ImportStatementPayload) => request<ImportPreview>('/api/v1/imports/preview', { method: 'POST', body: JSON.stringify(payload) }),
  importStatement: (payload: ImportStatementPayload & { idempotency_key: string }) =>
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
