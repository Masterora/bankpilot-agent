/** 助手对话、只读证据与服务端冻结的预算提案。 */
import type {
  BudgetInput,
  BudgetItem,
  BudgetWorkspace,
  RecurringWorkspace,
} from '../planning/types'
import type { OverviewSnapshot } from '../../types'
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
  | { tool: 'budgets'; month: string; data: Omit<BudgetWorkspace, 'evidence'> }
  | { tool: 'recurring'; month: string; data: Omit<RecurringWorkspace, 'candidates'> }
  | { tool: 'overview'; month: string; data: Pick<OverviewSnapshot, 'summaries'> }
export interface Reply {
  text: string
  evidence: Evidence[]
  action: AssistantAction | null
}
