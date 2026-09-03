/**
 * 文件职责：验证应用级深色主题与中英文切换。
 * 主要内容：替换 localStorage 与 fetch，渲染未登录界面，断言主题、语言和持久化偏好。
 * 关键边界：测试不访问真实 API，每次执行后清理全局替身。
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

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

  afterEach(() => vi.unstubAllGlobals())

  it('uses the dark theme and switches between Chinese and English', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: '登录 BankPilot' })).toBeInTheDocument()
    expect(document.documentElement.dataset.theme).toBe('dark')

    fireEvent.click(screen.getByRole('button', { name: 'Switch to English' }))

    expect(screen.getByRole('heading', { name: 'Sign in to BankPilot' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en-US')
    expect(window.localStorage.getItem('bankpilot.locale')).toBe('en-US')
  })
})
