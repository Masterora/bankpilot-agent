/**
 * 文件职责：验证交易金额的本地化格式。
 * 主要内容：确认中文环境下 CNY 金额保留两位小数。
 * 关键边界：断言不依赖特定系统的货币符号样式。
 */

import { describe, expect, it } from 'vitest'

import { formatMoney } from './format'

describe('formatMoney', () => {
  it('formats CNY amounts deterministically', () => {
    expect(formatMoney('-128.50', 'CNY', 'zh-CN')).toContain('128.50')
  })
})
