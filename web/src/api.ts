/**
 * 文件职责：封装 Web 对同源 v1 API 的访问。
 * 主要内容：统一 Cookie、JSON 和错误处理；覆盖认证、导入、账本搜索、核查、关系、规划、月报及持久助手会话。
 * 关键边界：不持久保存密码或会话令牌；版本与幂等身份由调用方传入，业务事实由服务端裁决。
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

import type { AccountMonthReview } from './features/ledger/MonthReviews'
import type { ProjectionRequest, ReviewProjection } from './features/ledger/LedgerReviews'
import type { SearchFilters, SearchPage, SearchItem } from './features/ledger/search'
import type { Conversation } from './features/assistant/types'

import type { AssistantAction, TurnInput, SavedTurn, ConversationPage, ConversationDetail, SpendingPage, SpendingScope, SpendingSummary, ComparisonEvidencePage, SpendingCategoryComparison } from './features/assistant/types'

import type { BudgetCarryPreview, BudgetInput, BudgetWorkspace, DiscoveryDecisionPage, DiscoveryDecisionRequest, DiscoveryProposal, DiscoveryProposalRequest, RecurringDiscoveryPage, RecurringEditInput, RecurringInput, RecurringItem, RecurringTransaction, RecurringWorkspace } from './features/planning/types'
import type { AttentionPreference, AttentionResponse, AttentionStateRequest, AttentionType } from './features/overview/attention'


import type { NotificationPage } from './features/notifications/types'
import { announceSessionChange, invalidateSession, sessionIdentity } from './shared/sessionIdentity'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly targetPlanId?: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const expected = sessionIdentity()
  const bound = !/^\/api\/v1\/auth\/(?:me|login|register)$/.test(path)
  if (bound && !expected) throw new ApiError('Refresh the account before retrying', 409, 'session_identity_required')
  // 凭证由浏览器管理，避免应用 JavaScript 读取会话令牌。
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(path.startsWith('/api/v1/assistant') ? { 'X-Assistant-Protocol': '5' } : {}),
      ...init?.headers,
      ...(bound ? { 'X-BankPilot-User': expected! } : {}),
    },
  })
  if (bound && expected !== sessionIdentity()) throw new ApiError('Account changed', 409, 'session_identity_changed')
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (bound && expected !== sessionIdentity()) throw new ApiError('Account changed', 409, 'session_identity_changed')
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = body.detail
      if (
        typeof detail === 'object' && detail !== null &&
        'code' in detail && typeof detail.code === 'string' &&
        'message' in detail && typeof detail.message === 'string'
      ) {
        if ((response.status === 401 && bound) || detail.code === 'session_identity_changed' || detail.code === 'session_identity_required') invalidateSession()
        throw new ApiError(detail.message, response.status, detail.code,
          'target_plan_id' in detail && typeof detail.target_plan_id === 'string' ? detail.target_plan_id : undefined)
      }
    }
    throw new ApiError('服务响应格式无效', response.status, 'invalid_response')
  }
  if (init?.method && /\/search-(?:context|subscription)(?:\/seen)?$/.test(path)) window.dispatchEvent(new Event('bankpilot:query-subscription-changed'))
  if (init?.method === 'POST' && path.startsWith('/api/v1/attention/')) {
    window.dispatchEvent(new Event('bankpilot:attention-changed'))
  }
  if (init?.method === 'POST' && /^\/api\/v1\/(?:imports(?:\/[^/]+\/revoke)?|relations|accounts\/[^/]+\/name|transactions\/[^/]+\/category|runs\/[^/]+\/transactions\/[^/]+\/category)$/.test(path)) {
    window.dispatchEvent(new Event('bankpilot:ledger-changed'))
  } else if (init?.method === 'POST' && (/^\/api\/v1\/(?:budgets(?:\/copy|\/delete|\/carry)?|recurring(?:\/[^/]+\/(?:edit|status|match|skip|cancel-revision|cancel-status))?|assistant\/confirm)$/.test(path) || /^\/api\/v1\/recurring\/discovery\/proposals\/[^/]+\/confirm$/.test(path))) {
    window.dispatchEvent(new Event('bankpilot:planning-changed'))
  }
  if (response.status === 204) return undefined as T
  const result = response.headers.get('content-type')?.includes('text/csv') ? await response.text() : await response.json()
  if (bound && expected !== sessionIdentity()) throw new ApiError('Account changed', 409, 'session_identity_changed')
  return result as T
}

export const api = {
  accountExport: () => request<Record<string, unknown>>('/api/v1/auth/data-export', { method: 'POST' }),
  deleteAccount: (current_password: string, confirmation: string) => request<void>('/api/v1/auth/delete', { method: 'POST', body: JSON.stringify({ current_password, confirmation }) }),
  assistantSubscription: (id: string, enabled: boolean, expected_context_version: number) => request<Conversation>(`/api/v1/assistant/conversations/${id}/search-subscription`, { method: 'PUT', body: JSON.stringify({ enabled, expected_context_version }) }),
  assistantSubscriptionSeen: (id: string, changed_at: string) => request<void>(`/api/v1/assistant/conversations/${id}/search-subscription/seen`, { method: 'POST', body: JSON.stringify({ changed_at }) }),
  notificationAvailability: () => request<{ enabled: boolean }>('/api/v1/notifications/availability'),
  notifications: (cursor?: string) => request<NotificationPage>(`/api/v1/notifications${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`),
  notificationSeen: (id: string) => request<{ id: string; seen_at: string }>(`/api/v1/notifications/${id}/seen`, { method: 'POST' }),
  attention: (month: string, group: 'all' | 'budgets' | 'recurring' = 'all') => request<AttentionResponse>(`/api/v1/attention?month=${month}-01&group=${group}`),
  attentionPreferences: () => request<AttentionPreference[]>('/api/v1/attention/preferences'),
  attentionState: (payload: AttentionStateRequest) => request<{ operation_id: string; accepted_version: string; snoozed_until: string | null }>('/api/v1/attention/state', { method: 'POST', body: JSON.stringify(payload) }),
  attentionPreference: (type: AttentionType, payload: { operation_id: string; enabled: boolean; expected_version: number }) => request<{ operation_id: string; accepted_version: string }>(`/api/v1/attention/preferences/${type}`, { method: 'POST', body: JSON.stringify(payload) }),
  reviewProjection: (payload: ProjectionRequest) => request<ReviewProjection>('/api/v1/reviews/projection', { method: 'POST', body: JSON.stringify(payload) }),
  search: (filters: SearchFilters, offset = 0, version?: { expected_revision: number; expected_search_version: string }) => request<SearchPage>('/api/v1/transactions/search', { method: 'POST', body: JSON.stringify({ filters, offset, ...version }) }),
  searchExport: (page: SearchPage) => request<string>('/api/v1/transactions/search/export', { method: 'POST', body: JSON.stringify({ filters: page.filters, expected_revision: page.ledger_revision, expected_search_version: page.search_version }) }),
  transaction: (id: string, version?: { expected_revision: number; expected_search_version: string }) => request<{ item: SearchItem; ledger_revision: number; search_version: string }>(`/api/v1/transactions/${id}${version ? '?' + new URLSearchParams({ expected_revision: String(version.expected_revision), expected_search_version: version.expected_search_version }) : ''}`),
  assistantSearchContext: (id: string, filters: SearchFilters | null, expected_context_version: number) => request<Conversation>(`/api/v1/assistant/conversations/${id}/search-context`, { method: 'PUT', body: JSON.stringify({ filters, expected_context_version }) }),
  assistantTurn: (payload: TurnInput) => request<SavedTurn>('/api/v1/assistant/turns', { method: 'POST', body: JSON.stringify(payload) }),
  assistantLookup: (payload: Pick<TurnInput, 'request_id' | 'conversation_id' | 'creation_id'>) => request<SavedTurn>(`/api/v1/assistant/turns/${payload.request_id}?${new URLSearchParams(payload.conversation_id ? { conversation_id: payload.conversation_id } : { creation_id: payload.creation_id! })}`),
  assistantHistory: (cursor?: string) => request<ConversationPage>(`/api/v1/assistant/conversations${cursor ? `?cursor=${cursor}` : ''}`),
  assistantConversation: (id: string, before?: number) => request<ConversationDetail>(`/api/v1/assistant/conversations/${id}${before ? `?before=${before}` : ''}`),
  assistantDelete: (id: string) => request(`/api/v1/assistant/conversations/${id}/delete`, { method: 'POST' }),
  assistantScope: (id: string, month: string, spending_context: SpendingScope | null, expected_context_version: number) => request<Conversation>(`/api/v1/assistant/conversations/${id}/scope`, { method: 'POST', body: JSON.stringify({ month, spending_context, expected_context_version }) }),
  spendingEvidence: (summary: SpendingSummary, page: number) => {
    const params = new URLSearchParams({ ...summary.scope, expected_revision: String(summary.ledger_revision), expected_calculation_version: summary.calculation_version, page: String(page) })
    return request<SpendingPage>(`/api/v1/assistant/spending-evidence?${params}`)
  },
  comparisonEvidence: (turnId: string, side: 'baseline' | 'target', category: SpendingCategoryComparison['category'], page: number) => {
    const params = new URLSearchParams({ side, category, page: String(page) })
    return request<ComparisonEvidencePage>(`/api/v1/assistant/turns/${turnId}/comparison-evidence?${params}`)
  },
  assistantAction: (id: string, cancel: boolean) => request<AssistantAction>(`/api/v1/assistant/${cancel ? 'cancel' : 'confirm'}`, { method: 'POST', body: JSON.stringify({ id }) }),
  budgets: (month: string) => request<BudgetWorkspace>(`/api/v1/budgets?month=${month}-01`),
  saveBudget: (payload: BudgetInput) => request<void>('/api/v1/budgets', { method: 'POST', body: JSON.stringify(payload) }),
  deleteBudget: (payload: Omit<BudgetInput, 'amount'>) => request<void>('/api/v1/budgets/delete', { method: 'POST', body: JSON.stringify(payload) }),
  copyBudgets: (month: string) => request<{ copied: number; source_count: number }>('/api/v1/budgets/copy', { method: 'POST', body: JSON.stringify({ month: `${month}-01` }) }),
  budgetCarryPreview: (month: string) => request<BudgetCarryPreview>(`/api/v1/budgets/carry?month=${month}-01`),
  confirmBudgetCarry: (payload: {month: string; operation_id: string; fingerprint: string}) => request<BudgetCarryPreview>('/api/v1/budgets/carry', {method: 'POST', body: JSON.stringify(payload)}),
  recurring: (month: string) => request<RecurringWorkspace>(`/api/v1/recurring?month=${month}-01`),
  recurringCandidates: (month: string) => request<RecurringTransaction[]>(`/api/v1/recurring/candidates?month=${month}-01`),
  recurringDiscoveryAvailability: () => request<{ enabled: boolean }>('/api/v1/recurring/discovery/availability'),
  recurringDiscovery: (month: string, offset = 0, token?: string) => {
    const params = new URLSearchParams({ through: `${month}-01`, offset: String(offset) })
    if (token) params.set('discovery_snapshot_token', token)
    return request<RecurringDiscoveryPage>(`/api/v1/recurring/discovery?${params}`)
  },
  recurringDiscoveryDecisions: (status: 'ignored' | 'linked', offset = 0, token?: string) => {
    const params = new URLSearchParams({ status, offset: String(offset) })
    if (token) params.set('decision_snapshot_token', token)
    return request<DiscoveryDecisionPage>(`/api/v1/recurring/discovery/decisions?${params}`)
  },
  recurringDiscoveryEvidence: (key: string, month: string) => request<{ evidence_status: 'present' | 'missing' }>(`/api/v1/recurring/discovery/decisions/${key}/evidence?through=${month}-01`),
  recurringDiscoveryDecision: (payload: DiscoveryDecisionRequest) => request<{ operation_id: string; version: number; status: string }>('/api/v1/recurring/discovery/decisions', { method: 'POST', body: JSON.stringify(payload) }),
  recurringDiscoveryProposal: (payload: DiscoveryProposalRequest) => request<DiscoveryProposal>('/api/v1/recurring/discovery/proposals', { method: 'POST', body: JSON.stringify(payload) }),
  recurringDiscoveryProposalDetail: (id: string) => request<DiscoveryProposal>(`/api/v1/recurring/discovery/proposals/${id}`),
  recurringDiscoveryProposalConfirm: (id: string) => request<DiscoveryProposal>(`/api/v1/recurring/discovery/proposals/${id}/confirm`, { method: 'POST' }),
  createRecurring: (payload: RecurringInput) => request<void>('/api/v1/recurring', { method: 'POST', body: JSON.stringify(payload) }),
  editRecurring: (payload: RecurringEditInput) => request<void>(`/api/v1/recurring/${payload.id}/edit`, { method: 'POST', body: JSON.stringify(payload) }),
  recurringDraft: (id: string) => request<RecurringInput>(`/api/v1/recurring/draft?transaction_id=${id}`),
  skipRecurring: (id: string, due_date: string, skipped: boolean, expected_version: number) => request<void>(`/api/v1/recurring/${id}/skip`, { method: 'POST', body: JSON.stringify({ due_date, skipped, expected_version }) }),
  cancelRecurringRevision: (id: string, effective_month: string, expected_version: number) => request<void>(`/api/v1/recurring/${id}/cancel-revision`, { method: 'POST', body: JSON.stringify({ effective_month, expected_version }) }),
  monthReviews: (month: string) => request<AccountMonthReview[]>(`/api/v1/month-reviews?month=${month}-01`),
  changeMonthReview: (item: AccountMonthReview, action: 'review' | 'close' | 'reopen') => request<AccountMonthReview>(`/api/v1/month-reviews/${item.account_id}`, { method: 'POST', body: JSON.stringify({ month: item.month, action, expected_version: item.version, expected_revision: item.ledger_revision }) }),
  cancelRecurringStatus: (id: string, effective_date: string, expected_version: number) => request<void>(`/api/v1/recurring/${id}/cancel-status`, { method: 'POST', body: JSON.stringify({ effective_date, expected_version }) }),
  recurringStatus: (id: string, status: RecurringItem['status'], expected_version: number, effective_date?: string) => request<void>(`/api/v1/recurring/${id}/status`, { method: 'POST', body: JSON.stringify({ status, expected_version, effective_date }) }),
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
  saveReview: (start: string, end: string, key: string, state: ReviewItem['state'], note: string, expected_revision: number) => request<void>('/api/v1/reviews', { method: 'POST', body: JSON.stringify({ start_date: start, end_date: end, key, state, note, expected_revision }) }),
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
  changePassword: (current_password: string, new_password: string) => request<void>('/api/v1/auth/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }).then(() => announceSessionChange()),
  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),
  listAccounts: () => request<{ items: Account[] }>('/api/v1/accounts'),
  ledger: (start: string, end: string) => request<RunResult['transactions']>(`/api/v1/transactions?start_date=${start}&end_date=${end}`),
  correctLedgerCategory: (id: string, category: TransactionCategory, expected_revision: number) => request<void>(`/api/v1/transactions/${id}/category`, { method: 'POST', body: JSON.stringify({ category, expected_revision }) }),
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
  correctCategory: (runId: string, transactionId: string, category: TransactionCategory, expected_revision: number) =>
    request<Run>(`/api/v1/runs/${runId}/transactions/${transactionId}/category`, {
      method: 'POST',
      body: JSON.stringify({ category, expected_revision }),
    }),
  watchRunEvents: (
    runId: string,
    onEvent: (event: RunEvent) => void,
    onError: () => void,
  ) => {
    // EventSource 自动携带同源 Cookie，并使用 Last-Event-ID 恢复断开的事件流。
    const expected = sessionIdentity()
    if (!expected) throw new ApiError('Account changed', 409, 'session_identity_required')
    const source = new EventSource(`/api/v1/runs/${runId}/events?expected_user_id=${encodeURIComponent(expected)}`)
    source.onmessage = (message) => {
      if (expected !== sessionIdentity()) { source.close(); return }
      onEvent(JSON.parse(message.data) as RunEvent)
    }
    source.onerror = onError
    return source
  },
}
