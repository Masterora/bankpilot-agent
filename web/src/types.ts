/**
 * 文件职责：定义 Web 使用的核心 API 响应与写入类型。
 * 主要内容：用户卡片、导入、交易分类、关系和核查、运行事件、总览与月报；规划和助手类型位于各自模块。
 * 关键边界：金额保持服务端字符串，运行状态与版本字段须匹配服务端契约，前端类型不代替授权验证。
 */

export interface User {
  id: string
  email: string
}

export interface Account {
  id: string
  name: string
  currency: string
  source: string
}

export interface ImportFieldMapping {
  transaction_id?: string | null
  account?: string | null
  currency?: string | null
  occurred_at: string
  merchant: string
  amount: string
  description: string | null
}

export interface ImportRowError {
  row_number: number
  code: string
  message: string
}

export interface ImportBatch {
  source: string
  skipped_rows: number | null
  parser_version: string | null
  new_rows: number | null
  valid_rows: number | null
  issue_count: number | null
  issues_truncated: boolean | null
  excluded_truncated: boolean | null
  excluded: ImportRowError[]
  id: string
  account_id: string | null
  account_name: string
  currency: string
  file_name: string
  status: 'COMPLETED' | 'COMPLETED_WITH_DUPLICATES' | 'REJECTED' | 'REVOKED'
  total_rows: number
  imported_rows: number
  duplicate_rows: number
  error_rows: number
  start_date: string | null
  end_date: string | null
  field_mapping: ImportFieldMapping
  errors: ImportRowError[]
  created_at: string
}

export interface ImportBatchList {
  items: ImportBatch[]
}

export interface ImportStatementPayload {
  file_name: string
  content: string
  account_name: string
  account_id?: string | null
  currency: string
  mapping: ImportFieldMapping
}

export type RelationKind = 'duplicate' | 'transfer' | 'refund'
export interface TransactionRelation {
  id: string | null
  kind: RelationKind
  first_id: string
  second_id: string
  state: 'pending' | 'confirmed' | 'rejected' | 'revoked'
  version: number
  updated_at: string | null
}

export type RelationTransaction = Pick<Transaction, 'id' | 'booking_date' | 'occurred_at' | 'time_precision' | 'account_name' | 'merchant' | 'description' | 'amount' | 'currency' | 'import_batch_id' | 'source_row_number'> & { account_id: string }
export interface RelationWorkspace {
  items: TransactionRelation[]
  transactions: RelationTransaction[]
  truncated: boolean
  summaries: {
    currency: string
    raw_inflow: string
    raw_outflow: string
    adjusted_inflow: string
    adjusted_outflow: string
    adjusted_net: string
    duplicate_excluded: number
    transfer_excluded: number
    refund_amount: string
  }[]
}

export interface OverviewSnapshot {
  summaries: RelationWorkspace['summaries']
  recent_transactions: RelationTransaction[]
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
  time_precision?: 'unknown' | 'date' | 'timestamp'
  import_batch_id?: string | null
  source_row_number?: number | null
  id: string
  booking_date: string
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

export interface ReviewItem {
  key: string
  rule_id: 'large_outflow_v1' | 'possible_duplicate_v1'
  severity: 'notice' | 'warning'
  transaction_ids: string[]
  facts: Record<string, string>
  state: 'pending' | 'normal' | 'follow_up'
  note: string
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

export interface MonthlySnapshot {
  month: string
  ledger_revision: number
  report_rule_version: string
  transactions: RunResult['transactions']
  analysis: BillAnalysis
  review: BillReview
}

export interface MonthlyReport {
  id: string
  month: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'DELETED'
  attempts: number
  created_at: string
  completed_at: string | null
  ledger_revision: number | null
  rule_version: string | null
  error_code: string | null
  stale: boolean
}

export interface ReportDetail extends MonthlyReport {
  snapshot: MonthlySnapshot | null
}

export interface RunResult {
  message: string
  transactions: {
    ledger_revision?: number | null
    start_date: string
    end_date: string
    items: Transaction[]
  }
  analysis: BillAnalysis
  review: BillReview | null
}

/** 核查快照包含生成时关系和来源证据；缺失表示旧快照，不从当前账本补造。 */
export interface BillReview {
  snapshot_at: string
  rule_version: 'transaction_relations_v1'
  adjusted_summaries: RelationWorkspace['summaries']
  relations: TransactionRelation[]
  evidence: RelationTransaction[]
  candidates_truncated: boolean
  coverage: {
    status: 'unverified'
    start_date: string
    end_date: string
    transaction_count: number
    import_batch_count: number
  }
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

export interface ImportPreview {
  source: string
  parser_version: string
  request_digest: string
  currency: string
  total_rows: number
  valid_rows: number
  new_rows: number
  duplicate_rows: number
  error_rows: number
  skipped_rows: number
  issue_count: number
  issues_truncated: boolean
  excluded_truncated: boolean
  preview_truncated: boolean
  valid_amounts: { income: string; expense: string; net: string }
  new_amounts: { income: string; expense: string; net: string }
  errors: ImportRowError[]
  excluded: ImportRowError[]
  rows: {
    row_number: number
    date: string
    occurred_at: string
    time_precision: 'unknown' | 'date' | 'timestamp'
    merchant: string
    amount: string
    classification: 'new' | 'duplicate'
  }[]
}
