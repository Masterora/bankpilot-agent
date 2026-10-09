/**
 * 文件职责：建立 BankPilot React 应用的顶层会话与语言边界。
 *
 * 主要内容：恢复当前会话，在认证页与产品工作区之间切换，并同步全局语言和主题。
 * 关键边界：业务页面、跨页面状态和 API 细节分别由 feature、Workspace 与 api 模块负责。
 */

import { useEffect, useRef, useState } from 'react'

import { api, ApiError } from './api'
import { announceSessionChange, bindSessionIdentity, sessionChangeKey } from './shared/sessionIdentity'
import { Workspace } from './app/Workspace'
import { AuthPage } from './features/auth/AuthPage'
import { messages, storedLocale } from './i18n'
import type { Locale } from './i18n'
import { LoadingScreen } from './shared/ui'
import type { User } from './types'

export default function App() {
  // 语言是本地界面偏好；认证状态仍由服务端通过 HttpOnly Cookie 管理。
  const [locale, setLocale] = useState<Locale>(storedLocale)
  const [user, setUser] = useState<User | null>(null)
  const [switchingAccount, setSwitchingAccount] = useState(false)
  const [checkingSession, setCheckingSession] = useState(true)
  const copy = messages[locale]
  const sessionSequence = useRef(0)

  useEffect(() => {
    document.documentElement.lang = locale
    document.documentElement.dataset.theme = 'dark'
    window.localStorage.setItem('bankpilot.locale', locale)
  }, [locale])

  useEffect(() => {
    let active = true
    async function refresh(clear = false) {
      const sequence = ++sessionSequence.current
      if (clear) { bindSessionIdentity(null); setUser(null); setCheckingSession(true); window.dispatchEvent(new Event('bankpilot-logout')) }
      try {
        const next = await api.me()
        if (!active || sequence !== sessionSequence.current) return
        bindSessionIdentity(next.id); setUser(next)
      } catch (cause) {
        if (active && sequence === sessionSequence.current && (clear || cause instanceof ApiError && cause.status === 401)) {
          bindSessionIdentity(null); setUser(null)
        }
      } finally {
        if (active && sequence === sessionSequence.current) setCheckingSession(false)
      }
    }
    const invalidated = () => { void refresh(true) }
    const storage = (event: StorageEvent) => { if (event.key === sessionChangeKey) invalidated() }
    const focus = () => { void refresh() }
    void refresh()
    window.addEventListener('bankpilot:session-invalidated', invalidated)
    window.addEventListener('storage', storage)
    window.addEventListener('focus', focus)
    return () => {
      active = false; sessionSequence.current += 1
      window.removeEventListener('bankpilot:session-invalidated', invalidated)
      window.removeEventListener('storage', storage)
      window.removeEventListener('focus', focus)
    }
  }, [])

  if (checkingSession) return <LoadingScreen label={copy.checkingSession} />
  if (!user) {
    return (
      <AuthPage
        copy={copy}
        locale={locale}
        onLocaleChange={setLocale}
        switchingAccount={switchingAccount}
        onAuthenticated={(nextUser) => { sessionSequence.current += 1; bindSessionIdentity(nextUser.id); announceSessionChange(); setSwitchingAccount(false); setUser(nextUser) }}
      />
    )
  }
  return (
    <Workspace
      key={user.id}
      copy={copy}
      locale={locale}
      onLocaleChange={setLocale}
      user={user}
      onLogout={(switchAccount = false) => { sessionSequence.current += 1; bindSessionIdentity(null); announceSessionChange(); setSwitchingAccount(switchAccount); setUser(null) }}
    />
  )
}
