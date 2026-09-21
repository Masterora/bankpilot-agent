/** 助手对话、只读证据与服务端冻结的预算提案。 */
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
  | { tool: 'spending'; month: string; data: SpendingSummary }
  | { tool: 'budgets'; month: string; data: Omit<BudgetWorkspace, 'evidence'> & { spending_refs: SpendingSummary[] } }
  | { tool: 'recurring'; month: string; data: Omit<RecurringWorkspace, 'candidates'> }
  | { tool: 'overview'; month: string; data: Pick<OverviewSnapshot, 'summaries'> }
export interface Reply {
  history_unavailable?: boolean
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
export interface EvidenceTarget { id: string; booking_date: string }

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
  protocol_version: 2
  request_id: string
  conversation_id?: string
  creation_id?: string
  question: string
  month: string
  locale: string
  spending_context: SpendingScope | null
  retry_of?: string
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
  reply: Reply | null
  error_code: string | null
}
export interface Conversation {
  id: string
  title: string
  month: string
  scope: SpendingScope | null
  created_at: string
  updated_at: string
}
export interface ConversationPage { items: Conversation[]; next_cursor: string | null; recent_id: string | null }
export interface ConversationDetail { conversation: Conversation; turns: SavedTurn[]; next_before: number | null; turn_limit: number }
