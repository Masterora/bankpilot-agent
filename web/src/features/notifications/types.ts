import type { AttentionType } from '../overview/attention'

export interface NotificationItem {
  id: string
  attention_type: AttentionType
  source_type: 'budget' | 'recurring'
  source_id: string
  source_date: string
  title: string
  created_at: string
  seen_at: string | null
}

export interface NotificationPage {
  query_changes: { conversation_id: string; title: string; filters: import('../ledger/search').SearchFilters; changed_at: string }[]
  items: NotificationItem[]
  server_time: string
  count_status: 'ready' | 'incomplete'
  unseen_count: number | null
  next_cursor: string | null
}
