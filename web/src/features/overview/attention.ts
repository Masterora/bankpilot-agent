export type AttentionType =
  | 'budget_near_limit'
  | 'budget_limit_reached'
  | 'budget_overspent'
  | 'recurring_upcoming'
  | 'recurring_unreviewed'
  | 'recurring_review_required'

export interface AttentionSource {
  source_type: 'budget' | 'recurring'
  source_id: string
  source_date: string
}

export interface AttentionItem {
  source: AttentionSource
  attention_type: AttentionType
  state: 'unread' | 'read' | 'snoozed'
  fact_token: string
  state_version: string
  title: string
  category: string | null
  currency: string
  amount: string
  current_amount: string | null
  snoozed_until: string | null
  tracking_gap: { reason: string; started_at: string; ended_at: string } | null
}

export interface AttentionPreference {
  attention_type: AttentionType
  enabled: boolean
  version: number
}

export interface AttentionGroup {
  status: 'ready' | 'unavailable'
  code: string | null
  retryable: boolean
  read_at: string
  unread: AttentionItem[]
  read: AttentionItem[]
  snoozed: AttentionItem[]
  disabled_count: number
  preferences: AttentionPreference[]
}

export interface AttentionResponse {
  month: string
  server_time: string
  next_refresh_at: string
  budgets: AttentionGroup | null
  recurring: AttentionGroup | null
}

export interface AttentionStateRequest extends AttentionSource {
  operation_id: string
  action: 'read' | 'snooze' | 'restore'
  fact_token: string
  expected_state_version: string
  snooze_option?: 'two_hours' | 'tomorrow_09' | 'seven_days_09'
}
