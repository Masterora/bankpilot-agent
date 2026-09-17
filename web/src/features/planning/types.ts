/** 文件职责：预算与周期扣款的接口类型；所有金额保留十进制字符串。 */
import type { TransactionCategory } from '../../types'

export interface BudgetItem {
  id: string
  category: TransactionCategory
  currency: string
  amount: string
  spent: string
  remaining: string
  overspent: boolean
  version: number
  transaction_count: number
}
export interface BudgetEvidence {
  transaction_id: string
  booking_date: string
  merchant: string
  account_name: string
  category: TransactionCategory
  currency: string
  amount: string
  contribution: string
  purchase: {
    id: string
    booking_date: string
    merchant: string
    account_name: string
    amount: string
  } | null
}
export interface BudgetWorkspace {
  month: string
  items: BudgetItem[]
  evidence: BudgetEvidence[]
  spending: {
    category: TransactionCategory
    currency: string
    spent: string
    transaction_count: number
  }[]
  coverage: {
    currency: string
    transaction_count: number
    latest_transaction_date: string | null
    limit: string
    budgeted_spent: string
    unbudgeted_spent: string
  }[]
  unbudgeted: {
    category: TransactionCategory
    currency: string
    spent: string
    transaction_count: number
  }[]
}
export interface BudgetInput {
  budget_id: string | null
  month: string
  category: TransactionCategory
  currency: string
  amount: string
  expected_version: number
}
export interface RecurringInput {
  id: string
  name: string
  merchant: string
  account_id: string
  currency: string
  amount: string
  cadence: 'monthly' | 'yearly'
  start_date: string
}
export interface RecurringEditInput extends RecurringInput {
  replace_revision?: boolean
  source_month: string
  effective_month: string
  expected_version: number
}
export interface RecurringTransaction {
  id: string
  account_id: string
  booking_date: string
  merchant: string
  amount: string
  currency: string
  eligible: boolean
}
export interface RecurringRevision extends Omit<RecurringInput, 'id' | 'name'> {
  effective_month: string
}
export interface RecurringItem extends RecurringInput {
  status: 'active' | 'paused' | 'ended'
  version: number
  latest_effective_month: string
  next_due_date: string | null
  future_revisions: RecurringRevision[]
  occurrences: { due_date: string; transaction: RecurringTransaction | null; skipped: boolean }[]
}
export interface RecurringWorkspace {
  month: string
  items: RecurringItem[]
  candidates: RecurringTransaction[]
}
