/**
 * 文件职责：验证账本筛选、导出和异常处理交互。
 * 主要内容：模拟隔离 API，检查核查结论保存、读取失败重试与 CSV 转义。
 * 关键边界：不访问远程 API，不写业务数据库。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { messages } from '../../i18n'
import type { Transaction } from '../../types'
import { LedgerPage } from './LedgerPage'
import { ledgerCsv } from './ledgerExport'

const item: Transaction = { id: 't1', booking_date: '2026-09-01', occurred_at: '2026-09-01T00:00:00Z', account_name: '验收账户', merchant: 'Store', description: 'memo', amount: '-1500.00', currency: 'CNY', category: 'other', category_source: 'rule', category_rule_id: 'other' }
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('escapes CSV text and keeps exact signed amounts', () => {
  const csv = ledgerCsv([{ ...item, merchant: '=HYPERLINK("unsafe")', description: 'two,columns\nnext line' }])
  expect(csv).toContain('"\'=HYPERLINK(""unsafe"")"')
  expect(csv).toContain(',-1500.00,')
  expect(csv).toContain('"two,columns\nnext line"')
})

it('saves and restores review decisions and filters merchants', async () => {
  vi.spyOn(api, 'ledger').mockResolvedValue({ start_date: '2026-09-01', end_date: '2026-09-05', items: [item] })
  const review = { key: 'a'.repeat(64), rule_id: 'large_outflow_v1' as const, severity: 'warning' as const, transaction_ids: ['t1'], facts: { threshold: '1000', currency: 'CNY' }, state: 'pending' as const, note: '' }
  const read = vi.spyOn(api, 'reviews').mockResolvedValue({ items: [review], summaries: [] })
  const save = vi.spyOn(api, 'saveReview').mockResolvedValue(undefined)
  const view = render(<LedgerPage copy={messages['zh-CN']} english={false} />)
  await screen.findByRole('heading', { name: '大额流出' })
  fireEvent.change(screen.getByLabelText('核查状态'), { target: { value: 'normal' } })
  fireEvent.change(screen.getByLabelText('核查备注'), { target: { value: '核对正常' } })
  fireEvent.click(screen.getByRole('button', { name: '保存结论' }))
  await screen.findByText('已保存')
  expect(save).toHaveBeenCalledWith(expect.any(String), expect.any(String), review.key, 'normal', '核对正常')
  view.unmount()
  read.mockResolvedValue({ items: [{ ...review, state: 'normal', note: '核对正常' }], summaries: [] })
  render(<LedgerPage copy={messages['zh-CN']} english={false} />)
  expect(await screen.findByLabelText('核查状态')).toHaveValue('normal')
  expect(screen.getByLabelText('核查备注')).toHaveValue('核对正常')
  fireEvent.change(screen.getByLabelText('商户或备注'), { target: { value: '不存在' } })
  expect(screen.getByText('暂无匹配交易')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '导出筛选结果 CSV' })).toBeDisabled()
})

it('retries failed reads and rejects an inverted date range', async () => {
  const read = vi.spyOn(api, 'ledger').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ start_date: '', end_date: '', items: [] })
  vi.spyOn(api, 'reviews').mockResolvedValue({ items: [], summaries: [] })
  render(<LedgerPage copy={messages['zh-CN']} english={false} />)
  fireEvent.click(await screen.findByRole('button', { name: '读取失败，重试' }))
  await screen.findByText('暂无匹配交易')
  expect(read).toHaveBeenCalledTimes(2)
  fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2099-01-01' } })
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('请选择有效期间'))
  expect(read).toHaveBeenCalledTimes(2)
})
