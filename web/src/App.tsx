/**
 * 文件职责：组装 BankPilot Web 的登录页、账单工作台与运行结果界面。
 *
 * 主要内容：
 * - `App`：恢复会话、管理语言，并在登录页与工作台之间切换。
 * - `Login`：提交账号密码并处理认证错误。
 * - `Workspace`：创建 Agent 运行、轮询终态、处理退出。
 * - `RunPanel`：展示交易结果、状态与审计时间线。
 * - `LanguageSwitch`：切换中英文界面。
 *
 * 关键边界：前端不读取会话令牌；轮询仅持续到 SUCCEEDED、FAILED 或 UNKNOWN。
 */

import { FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError, api } from './api'
import { formatDate, formatMoney } from './format'
import { isPresetQuery, messages, storedLocale } from './i18n'
import type { Locale, Messages } from './i18n'
import type { Run, User } from './types'

const terminalStatuses = new Set(['SUCCEEDED', 'FAILED', 'UNKNOWN'])

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
    return <Login copy={copy} locale={locale} onLocaleChange={setLocale} onLogin={setUser} />
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

interface LanguageProps {
  copy: Messages
  locale: Locale
  onLocaleChange: (locale: Locale) => void
}

function LanguageSwitch({ copy, locale, onLocaleChange }: LanguageProps) {
  return (
    <div className="language-switch" role="group" aria-label={copy.languageLabel}>
      <button
        type="button"
        aria-label={copy.switchToChinese}
        aria-pressed={locale === 'zh-CN'}
        onClick={() => onLocaleChange('zh-CN')}
      >
        中文
      </button>
      <button
        type="button"
        aria-label={copy.switchToEnglish}
        aria-pressed={locale === 'en-US'}
        onClick={() => onLocaleChange('en-US')}
      >
        EN
      </button>
    </div>
  )
}

interface LoginProps extends LanguageProps {
  onLogin: (user: User) => void
}

function Login({ copy, locale, onLocaleChange, onLogin }: LoginProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      onLogin(await api.login(email, password))
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 401
          ? copy.invalidCredentials
          : copy.loginFailed,
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-shell">
      <section className="login-intro">
        <div className="brand"><Logo /> BankPilot</div>
        <div className="intro-copy">
          <p className="eyebrow">{copy.loginEyebrow}</p>
          <h1>{copy.loginTitle}</h1>
          <p>{copy.loginDescription}</p>
        </div>
        <p className="security-note">{copy.securityNote}</p>
      </section>
      <section className="login-panel">
        <div className="login-panel-actions">
          <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
        </div>
        <form className="login-card" onSubmit={submit}>
          <div>
            <p className="eyebrow">{copy.secureAccess}</p>
            <h2>{copy.loginHeading}</h2>
            <p className="muted">{copy.loginHint}</p>
          </div>
          <label>
            {copy.email}
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            {copy.password}
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
              required
            />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" disabled={submitting}>
            {submitting ? copy.loggingIn : copy.login}
          </button>
        </form>
      </section>
    </main>
  )
}

interface WorkspaceProps extends LanguageProps {
  user: User
  onLogout: () => void
}

function Workspace({ copy, locale, onLocaleChange, user, onLogout }: WorkspaceProps) {
  const [message, setMessage] = useState(copy.defaultQuery)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const pollTimer = useRef<number | null>(null)

  useEffect(() => {
    setMessage((current) => (isPresetQuery(current) ? copy.defaultQuery : current))
  }, [copy])

  useEffect(() => () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current)
  }, [])

  async function poll(runId: string) {
    // 仅轮询到持久化终态出现，随后立即释放定时器。
    try {
      const current = await api.getRun(runId)
      setRun(current)
      if (!terminalStatuses.has(current.status)) {
        pollTimer.current = window.setTimeout(() => void poll(runId), 700)
      } else {
        setSubmitting(false)
      }
    } catch {
      setError(copy.queryStatusFailed)
      setSubmitting(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!message.trim()) return
    setError('')
    setRun(null)
    setSubmitting(true)
    try {
      const created = await api.createRun(message.trim())
      setRun(created)
      await poll(created.id)
    } catch {
      setError(copy.createRunFailed)
      setSubmitting(false)
    }
  }

  async function logout() {
    // 即使远程 Cookie 已过期，也要清理本地会话界面状态。
    await api.logout().catch(() => undefined)
    onLogout()
  }

  return (
    <main className="workspace-shell">
      <header>
        <div className="brand"><Logo /> BankPilot</div>
        <div className="header-actions">
          <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
          <div className="account-chip">
            <span>{user.email}</span>
            <button onClick={logout}>{copy.logout}</button>
          </div>
        </div>
      </header>
      <section className="hero">
        <p className="eyebrow">{copy.workspaceEyebrow}</p>
        <h1>{copy.workspaceTitle}</h1>
        <p>{copy.workspaceDescription}</p>
        <form className="prompt" onSubmit={submit}>
          <input
            aria-label={copy.queryInputLabel}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={1000}
          />
          <button className="primary" disabled={submitting}>
            {submitting ? copy.querying : copy.startQuery}
          </button>
        </form>
        <div className="suggestions">
          {copy.suggestions.map((item) => (
            <button key={item} onClick={() => setMessage(item)}>{item}</button>
          ))}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      <RunPanel copy={copy} locale={locale} run={run} />
    </main>
  )
}

function RunPanel({ copy, locale, run }: { copy: Messages; locale: Locale; run: Run | null }) {
  if (!run) {
    return <section className="empty-state"><span>⌁</span><p>{copy.emptyResult}</p></section>
  }
  const transactions = run.result?.transactions.items ?? []
  const resultMessage = run.result
    ? copy.resultSummary(
        run.result.transactions.start_date,
        run.result.transactions.end_date,
        transactions.length,
      )
    : statusLabel(run.status, copy)
  return (
    <section className="results-grid">
      <article className="result-card">
        <div className="result-heading">
          <div><p className="eyebrow">{copy.resultEyebrow}</p><h2>{resultMessage}</h2></div>
          <Status copy={copy} status={run.status} />
        </div>
        {run.error_message && <p className="error">{run.error_code}: {run.error_message}</p>}
        {transactions.length > 0 && (
          <div className="transaction-list">
            {transactions.map((item) => (
              <div className="transaction" key={item.id}>
                <div className="merchant-mark">{item.merchant.slice(0, 1)}</div>
                <div className="transaction-copy">
                  <strong>{item.merchant}</strong>
                  <span>{item.description} · {formatDate(item.occurred_at, locale)}</span>
                </div>
                <strong className={Number(item.amount) >= 0 ? 'income' : ''}>
                  {formatMoney(item.amount, item.currency, locale)}
                </strong>
              </div>
            ))}
          </div>
        )}
      </article>
      <aside className="timeline-card">
        <p className="eyebrow">{copy.timelineEyebrow}</p>
        <ol>
          {run.events.map((event) => (
            <li key={event.sequence}><span />{eventLabel(event.event_type, copy)}</li>
          ))}
        </ol>
      </aside>
    </section>
  )
}

function Status({ copy, status }: { copy: Messages; status: Run['status'] }) {
  return <span className={`status status-${status.toLowerCase()}`}>{statusLabel(status, copy)}</span>
}

function statusLabel(status: Run['status'], copy: Messages) {
  return copy.statuses[status]
}

function eventLabel(event: string, copy: Messages) {
  return copy.events[event] ?? event
}

function Logo() {
  return <span className="logo" aria-hidden="true"><i /><i /><i /></span>
}

function LoadingScreen({ label }: { label: string }) {
  return <main className="loading-screen"><Logo /><p>{label}</p></main>
}
