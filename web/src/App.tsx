/**
 * 文件职责：建立 BankPilot React 应用的顶层会话与语言边界。
 *
 * 主要内容：恢复当前会话，在认证页与产品工作区之间切换，并同步全局语言和主题。
 * 关键边界：业务页面、跨页面状态和 API 细节分别由 feature、Workspace 与 api 模块负责。
 */

import { useEffect, useState } from 'react'

import { api } from './api'
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
  const [checkingSession, setCheckingSession] = useState(true)
  const copy = messages[locale]

  useEffect(() => {
    document.documentElement.lang = locale
    document.documentElement.dataset.theme = 'dark'
    window.localStorage.setItem('bankpilot.locale', locale)
  }, [locale])

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setCheckingSession(false))
  }, [])

  if (checkingSession) return <LoadingScreen label={copy.checkingSession} />
  if (!user) {
    return (
      <AuthPage
        copy={copy}
        locale={locale}
        onLocaleChange={setLocale}
        onAuthenticated={setUser}
      />
    )
  }
  return (
    <Workspace
      copy={copy}
      locale={locale}
      onLocaleChange={setLocale}
      user={user}
      onLogout={() => setUser(null)}
    />
  )
}
