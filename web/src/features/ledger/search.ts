/**
 * 文件职责：定义前端搜索契约与已执行条件的地址恢复。
 * 主要内容：过滤和结果类型、版本参数、错误文案、条件标签以及 URL hash 读写。
 * 关键边界：只保存已提交条件，不存凭据或文件；金额保留字符串，真实匹配与版本校验在服务端。
 */
import type { Transaction, TransactionCategory } from '../../types'
import type { ReviewPeriod } from '../../shared/period'
import { apiErrorMessage } from '../../shared/apiErrors'

export interface SearchFilters {
  start_date: string; end_date: string; account_id?: string | null; currency?: string | null
  direction?: 'all' | 'debit' | 'credit'; min_amount?: string | null; max_amount?: string | null
  text?: string; text_scope?: 'merchant' | 'merchant_or_note'; category?: TransactionCategory | null
  import_batch_id?: string | null
}
export interface SearchItem extends Transaction { account_id: string; relation_kinds: string[] }
export interface SearchPage {
  filters: SearchFilters; total_count: number; items: SearchItem[]; offset: number; has_more: boolean
  ledger_revision: number; search_version: string
}
export const versions = (page: Pick<SearchPage, 'ledger_revision' | 'search_version'>) => ({ expected_revision: page.ledger_revision, expected_search_version: page.search_version })
export const periodFilters = (period: ReviewPeriod): SearchFilters => ({ start_date: period.start, end_date: period.end })
export function searchError(error: unknown, en: boolean) {
  return apiErrorMessage(error, en, {
    search_stale: ['账本已更新，请重新查询。', 'Ledger updated. Query again.'],
    search_capacity_exceeded: ['范围过大，请缩小日期或选择账户。', 'Too broad. Narrow the dates or choose an account.'],
    search_filter_unavailable: ['账户或批次不可用，请重新选择。', 'Account or batch unavailable. Select again.'],
    transaction_not_found: ['流水已不可用。', 'Transaction unavailable.'],
    assistant_context_stale: ['条件已在其他页面修改，请重新打开会话并选择。', 'Context changed elsewhere. Reopen the conversation and select again.'],
  })
}
export function readSearch(period: ReviewPeriod): SearchFilters {
  const raw = new URLSearchParams(window.location.hash.slice(1)).get('search')
  if (raw) { try { return { ...JSON.parse(raw), ...periodFilters(period) } } catch { /* Use the current period. */ } }
  return periodFilters(period)
}
export function writeSearch(filters: SearchFilters) {
  const params = new URLSearchParams(window.location.hash.slice(1))
  params.set('search', JSON.stringify(filters))
  params.set('start', filters.start_date)
  params.set('end', filters.end_date)
  const hash = `#${params}`
  if (window.location.hash !== hash) window.history.pushState(null, '', hash)
}

export function searchChips(filters: SearchFilters, categories: Record<TransactionCategory, string>, en: boolean) {
  return [
    ...(filters.text ? [{ key: 'text', label: filters.text }] : []),
    ...(filters.account_id ? [{ key: 'account_id', label: en ? 'Selected account' : '所选账户' }] : []),
    ...(filters.currency ? [{ key: 'currency', label: filters.currency }] : []),
    ...(filters.direction && filters.direction !== 'all' ? [{ key: 'direction', label: filters.direction === 'debit' ? (en ? 'Debit' : '支出') : (en ? 'Credit' : '收入') }] : []),
    ...(filters.min_amount ? [{ key: 'min_amount', label: `≥ ${filters.min_amount}` }] : []),
    ...(filters.max_amount ? [{ key: 'max_amount', label: `≤ ${filters.max_amount}` }] : []),
    ...(filters.category ? [{ key: 'category', label: categories[filters.category] }] : []),
    ...(filters.import_batch_id ? [{ key: 'import_batch_id', label: en ? 'Selected import' : '所选导入批次' }] : []),
    ...(filters.text_scope === 'merchant' ? [{ key: 'text_scope', label: en ? 'Merchant only' : '仅商户' }] : []),
  ]
}
