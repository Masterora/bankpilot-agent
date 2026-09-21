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
  expires_at: string
  result: BudgetItem | null
}
export type Evidence =
  | { tool: 'spending'; month: string; data: SpendingSummary }
  | { tool: 'budgets'; month: string; data: Omit<BudgetWorkspace, 'evidence'> & { spending_refs: SpendingSummary[] } }
  | { tool: 'recurring'; month: string; data: Omit<RecurringWorkspace, 'candidates'> }
  | { tool: 'overview'; month: string; data: Pick<OverviewSnapshot, 'summaries'> }
export interface Reply {
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
