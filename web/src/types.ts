/**
 * 文件职责：定义 Web 层消费的 BankPilot v1 查询、分析、事件流与修正类型。
 *
 * 主要内容：
 * - `User`：当前登录用户。
 * - `Transaction` / `BillAnalysis` / `RunResult`：分类交易、统计和异常结果。
 * - `RunEvent`：审计时间线事件。
 * - `Run`：包含状态、结果、错误与事件的完整运行快照。
 *
 * 关键边界：`Run.status` 与服务端持久化状态集必须保持一致。
 */

export interface User {
  id: string
  email: string
}

export type TransactionCategory =
  | 'income'
  | 'groceries'
  | 'dining'
  | 'transport'
  | 'shopping'
  | 'housing'
  | 'utilities'
  | 'entertainment'
  | 'healthcare'
  | 'education'
  | 'travel'
  | 'transfer'
  | 'other'

export interface Transaction {
  id: string
  occurred_at: string
  merchant: string
  description: string
  amount: string
  currency: string
  account_name: string
  category: TransactionCategory
  category_source: 'rule' | 'user'
  category_rule_id: string
}

export interface CurrencySummary {
  currency: string
  income: string
  expense: string
  net: string
  transaction_count: number
}

export interface CategorySummary {
  category: TransactionCategory
  currency: string
  amount: string
  transaction_count: number
}

export interface BillAnomaly {
  rule_id: 'large_outflow_v1' | 'possible_duplicate_v1'
  severity: 'notice' | 'warning'
  transaction_ids: string[]
  facts: Record<string, string>
}

export interface BillAnalysis {
  currency_summaries: CurrencySummary[]
  category_summaries: CategorySummary[]
  anomalies: BillAnomaly[]
}

export interface RunResult {
  message: string
  transactions: {
    start_date: string
    end_date: string
    items: Transaction[]
  }
  analysis: BillAnalysis
}

export interface RunEvent {
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  occurred_at: string
}

export interface Run {
  id: string
  status: 'CREATED' | 'PLANNING' | 'EXECUTING' | 'SUCCEEDED' | 'FAILED' | 'UNKNOWN'
  user_message: string
  result: RunResult | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  events: RunEvent[]
}
