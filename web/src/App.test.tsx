/**
 * 文件职责：验证应用主题、语言以及账单分析与分类修正界面。
 * 主要内容：替换 localStorage 与 fetch，覆盖未登录偏好和已登录账单分析流程。
 * 关键边界：测试不访问真实 API，每次执行后清理全局替身。
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { Run } from './types'

describe('App language and theme', () => {
  beforeEach(() => {
    const values = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        removeItem: (key: string) => values.delete(key),
        setItem: (key: string, value: string) => values.set(key, value),
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Unauthorized' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the dark theme and switches between Chinese and English', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: '登录 BankPilot' })).toBeInTheDocument()
    expect(document.documentElement.dataset.theme).toBe('dark')

    fireEvent.click(screen.getByRole('button', { name: 'Switch to English' }))

    expect(screen.getByRole('heading', { name: 'Sign in to BankPilot' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en-US')
    expect(window.localStorage.getItem('bankpilot.locale')).toBe('en-US')
  })

  it('renders deterministic analysis and saves a category correction', async () => {
    const run = buildRun('groceries')
    const corrected = buildRun('dining')
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/auth/me') {
        return jsonResponse({ id: 'user-1', email: 'owner@example.com' })
      }
      if (path === '/api/v1/runs' && init?.method === 'POST') return jsonResponse(run, 202)
      if (path.endsWith('/category') && init?.method === 'POST') return jsonResponse(corrected)
      return jsonResponse({ detail: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByRole('heading', { name: '查询账单' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '开始查询' }))
    expect(screen.getByRole('button', { name: '处理中…' })).toBeDisabled()
    expect(document.querySelector('.button-spinner')).toBeInTheDocument()
    expect(await screen.findByText('确定性统计')).toBeInTheDocument()
    expect(screen.getAllByText('日用百货')).not.toHaveLength(0)

    const category = screen.getByRole('combobox', { name: '交易分类: 社区超市' })
    fireEvent.change(category, { target: { value: 'dining' } })

    await waitFor(() => expect(category).toHaveValue('dining'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/runs/run-1/transactions/transaction-1/category',
      expect.objectContaining({ body: JSON.stringify({ category: 'dining' }), method: 'POST' }),
    )
  })
})

function buildRun(category: 'groceries' | 'dining'): Run {
  return {
    id: 'run-1',
    status: 'SUCCEEDED',
    user_message: '查询本月账单',
    result: {
      message: '查询完成',
      transactions: {
        start_date: '2026-09-01',
        end_date: '2026-09-03',
        items: [
          {
            id: 'transaction-1',
            occurred_at: '2026-09-02T08:00:00Z',
            merchant: '社区超市',
            description: '日用品',
            amount: '-128.50',
            currency: 'CNY',
            account_name: '日常账户',
            category,
            category_source: category === 'dining' ? 'user' : 'rule',
            category_rule_id:
              category === 'dining' ? 'category_user_override_v1' : 'category_groceries_v1',
          },
        ],
      },
      analysis: {
        currency_summaries: [
          {
            currency: 'CNY',
            income: '0.00',
            expense: '128.50',
            net: '-128.50',
            transaction_count: 1,
          },
        ],
        category_summaries: [
          { category, currency: 'CNY', amount: '128.50', transaction_count: 1 },
        ],
        anomalies: [],
      },
    },
    error_code: null,
    error_message: null,
    created_at: '2026-09-03T08:00:00Z',
    updated_at: '2026-09-03T08:00:01Z',
    events: [],
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
