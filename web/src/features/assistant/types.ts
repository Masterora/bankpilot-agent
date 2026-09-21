/**
 * 文件职责：定义助手界面消费的对话和证据类型。
 * 主要内容：会话轮次、消费与搜索上下文、工具证据、冻结预算提案及账本详情定位。
 * 关键边界：与服务端契约保持一致，不把展示类型当成权限或写入校验。
 */
import type { SearchFilters, SearchPage } from '../ledger/search'
import type {
  BudgetEvidence,
  BudgetInput,
  BudgetItem,
  BudgetWorkspace,
  RecurringWorkspace,
} from '../planning/types'
import type { TransactionCategory, OverviewSnapshot } from '../../types'
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}
export interface AssistantAction {
  id: string
  payload: BudgetInput
  before_amount: string | null
  status: 'pending' | 'applied' | 'cancelled'
  effective_status: 'pending' | 'applied' | 'cancelled' | 'expired' | 'conflict' | 'unavailable'
  can_confirm: boolean
  expires_at: string
  result: BudgetItem | null
}
export type Evidence =
  | { tool: 'find_transactions'; data: SearchPage }
  | { tool: 'spending'; month: string; data: SpendingSummary }
  | { tool: 'budgets'; month: string; data: Omit<BudgetWorkspace, 'evidence'> & { spending_refs: SpendingSummary[] } }
  | { tool: 'recurring'; month: string; data: Omit<RecurringWorkspace, 'candidates'> }
  | { tool: 'overview'; month: string; data: Pick<OverviewSnapshot, 'summaries'> }
  | { tool: 'compare_spending'; data: SpendingComparison }
export interface Reply {
  assistant_result_unavailable?: boolean
  text: string
  evidence: Evidence[]
  action: AssistantAction | null
}

export interface SpendingScope {
  month: string
  category: Exclude<TransactionCategory, 'income'>
  currency: string
}
export interface SpendingSummary {
  scope: SpendingScope
  ledger_revision: number
  calculation_version: string
  calculated_at: string
  gross_spending: string
  refund_offset: string
  net_spending: string
  contribution_count: number
  coverage: { transaction_count: number; latest_transaction_date: string | null }
}
export interface SpendingPage {
  summary: SpendingSummary
  page: number
  page_size: number
  total: number
  items: BudgetEvidence[]
}
export interface SpendingComparisonPeriod {
  month: string
  start_date: string
  end_date: string
  gross_spending: string
  refund_offset: string
  net_spending: string
  contribution_count: number
  coverage: { transaction_count: number; earliest_transaction_date: string | null; latest_transaction_date: string | null }
}
export interface SpendingCategoryComparison {
  category: TransactionCategory
  baseline_gross: string
  baseline_refund: string
  baseline_net: string
  baseline_count: number
  target_gross: string
  target_refund: string
  target_net: string
  target_count: number
  delta: string
}
export interface SpendingComparison {
  scope: { baseline_month: string; target_month: string; currency: string }
  baseline: SpendingComparisonPeriod
  target: SpendingComparisonPeriod
  gross_delta: string
  refund_delta: string
  net_delta: string
  categories: SpendingCategoryComparison[]
  data_status: 'comparable' | 'baseline_missing' | 'target_missing' | 'both_missing'
  ledger_revision: number
  calculation_version: string
  comparison_version: string
  calculated_at: string
}
export interface ComparisonEvidencePage {
  comparison: SpendingComparison
  side: 'baseline' | 'target'
  category: TransactionCategory
  page: number
  page_size: number
  total: number
  items: BudgetEvidence[]
}
export interface EvidenceTarget { id: string; booking_date: string; version?: { expected_revision: number; expected_search_version: string } }

export function spendingRefs(evidence: Evidence[]): SpendingSummary[] {
  const refs = evidence.flatMap(item => item.tool === 'spending' ? [item.data] : item.tool === 'budgets' ? item.data.spending_refs : [])
  const unique = new Map<string, SpendingSummary>()
  for (const ref of refs) {
    const { month, category, currency } = ref.scope
    unique.set(`${month}:${category}:${currency}:${ref.ledger_revision}:${ref.calculation_version}`, ref)
  }
  return [...unique.values()]
}

export interface TurnInput {
  protocol_version: 4
  expected_context_version: number
  request_id: string
  conversation_id?: string
  creation_id?: string
  question: string
  month: string
  locale: string
  spending_context: SpendingScope | null
  retry_of?: string
  recompare_of?: string
}
export interface SavedTurn {
  id: string
  conversation_id: string
  request_id: string
  sequence: number
  question: string
  month: string
  scope: SpendingScope | null
  status: 'processing' | 'completed' | 'failed'
  created_at: string
  completed_at: string | null
  result_version: number
  recompare_of: string | null
  reply: Reply | null
  error_code: string | null
}
export interface Conversation {
  search_context: SearchFilters | null
  context_version: number
  id: string
  title: string
  month: string
  scope: SpendingScope | null
  created_at: string
  updated_at: string
}
export interface ConversationPage { items: Conversation[]; next_cursor: string | null; recent_id: string | null }
export interface ConversationDetail { conversation: Conversation; turns: SavedTurn[]; next_before: number | null; turn_limit: number }
