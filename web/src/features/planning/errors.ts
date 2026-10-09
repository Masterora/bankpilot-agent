/**
 * 文件职责：将规划业务错误码转换为中英文提示。
 * 主要内容：预算版本冲突、周期配置锁定、匹配和未来修订等错误文案。
 * 关键边界：只负责展示；未覆盖状态交给共享错误处理，不暴露内部异常原文。
 */
import { apiErrorMessage } from '../../shared/apiErrors'

const errors: Record<string, [string, string]> = {
  budget_carry_month: ['只能结转已结束的上月预算，请选择 1900 年 2 月至本月。', 'Choose February 1900 through this month; the source month must be complete.'],
  budget_carry_applied: ['本月已结转，请重新读取回执；不能重复增加额度。', 'This month was already carried over. Reload the receipt.'],
  budget_carry_empty: ['上月没有可结转的剩余额度。', 'No remaining budget to carry over.'],
  budget_carry_amount_limit: ['结转后的预算超出金额上限。', 'The resulting budget exceeds the amount limit.'],
  planning_revision_locked: [
    '该计划已生效或已有核对结果，不能改写；请安排后续变更。',
    'This configuration is effective or reviewed. Schedule a later change.',
  ],
  planning_skipped: [
    '本期已确认未发生，请先撤回该确认。',
    'Undo the skipped confirmation before linking.',
  ],
  planning_not_due: [
    '尚未到预计日期，不能确认本期未发生。',
    'Wait until the due date to confirm no charge occurred.',
  ],
  planning_stale: ['数据已变化，请刷新后重试。', 'Data changed. Refresh and retry.'],
  planning_not_found: ['记录已不存在，请刷新。', 'Record unavailable. Please refresh.'],
  planning_already_linked: [
    '流水或期次已关联，请刷新后核对。',
    'Transaction or occurrence already linked. Refresh to review.',
  ],
  planning_match_invalid: [
    '该流水不符合账户、币种或有效支出要求。',
    'Select an eligible expense in the same account and currency.',
  ],
  planning_inactive: [
    '请先恢复跟踪，再关联流水。',
    'Resume this plan before linking a transaction.',
  ],
  planning_effective_month: [
    '生效月份不能早于本月，且须晚于上一版配置及已核对月份。周期起始日不能晚于生效月份。',
    'Choose this month or later, after the latest configuration and reviewed occurrences. The schedule must start by that month.',
  ],
  planning_ended: ['此固定支出已结束。', 'This plan has ended.'],
  planning_period_limit: [
    '当月交易超过 10,000 笔，暂无法读取完整规划数据。',
    'This month exceeds the 10,000 transaction limit.',
  ],
  planning_currency: ['币种与账户不一致。', 'Currency must match the account.'],
  planning_conflict: ['操作标识冲突，请刷新核对。', 'Operation conflict. Refresh to review.'],
}
export function planningError(error: unknown, english: boolean): string {
  return apiErrorMessage(error, english, errors)
}
