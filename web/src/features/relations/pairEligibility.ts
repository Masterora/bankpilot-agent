/**
 * 文件职责：预筛人工交易配对的可选事实。
 * 主要内容：比较币种、金额、日期和账户等候选条件。
 * 关键边界：金额只用整数分比较；预筛不替代服务端的关系和并发校验。
 */
import type { RelationKind, RelationTransaction } from '../../types'

/** Decimal strings are converted to integer cents only for eligibility comparisons. */
export function cents(value: string) {
  const negative = value.startsWith('-')
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return negative ? -amount : amount
}
export function eligiblePair(
  kind: RelationKind,
  first: RelationTransaction,
  second: RelationTransaction,
) {
  if (first.id === second.id || first.currency !== second.currency) return false
  const a = cents(first.amount),
    b = cents(second.amount)
  const days = (Date.parse(second.booking_date) - Date.parse(first.booking_date)) / 86400000
  if (kind === 'duplicate')
    return (
      a !== 0n && a === b && Math.abs(days) <= 1 && first.import_batch_id !== second.import_batch_id
    )
  if (kind === 'transfer')
    return a < 0n && b === -a && first.account_id !== second.account_id && Math.abs(days) <= 3
  return (
    a < 0n &&
    b > 0n &&
    b <= -a &&
    days >= 0 &&
    days <= 90 &&
    !(
      first.time_precision === 'timestamp' &&
      second.time_precision === 'timestamp' &&
      Date.parse(second.occurred_at!) < Date.parse(first.occurred_at!)
    )
  )
}

/** Exclude conflicts visible in this snapshot. Server rechecks under its write lock. */
export function conflictFree(
  kind: RelationKind,
  first: RelationTransaction,
  second: RelationTransaction,
  confirmed: import('../../types').TransactionRelation[],
  transactions: RelationTransaction[],
) {
  let refund = cents(second.amount)
  for (const relation of confirmed) {
    if (relation.state !== 'confirmed') continue
    const ids = [first.id, second.id]
    if (!ids.includes(relation.first_id) && !ids.includes(relation.second_id)) continue
    if (kind === 'duplicate') {
      if (
        [relation.first_id, relation.second_id].includes(second.id) ||
        (relation.kind === 'duplicate' && first.id === relation.second_id)
      )
        return false
    } else if (relation.kind === 'duplicate') {
      if (ids.includes(relation.second_id)) return false
    } else if (
      kind === 'refund' &&
      relation.kind === 'refund' &&
      first.id === relation.first_id &&
      second.id !== relation.second_id
    ) {
      const linked = transactions.find((row) => row.id === relation.second_id)
      if (!linked) return false
      refund += cents(linked.amount)
    } else return false
  }
  return kind !== 'refund' || refund <= -cents(first.amount)
}
