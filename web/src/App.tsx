/**
 * 文件职责：组装 BankPilot Web 的登录页、账单工作台与运行结果界面。
 *
 * 主要内容：
 * - `App`：恢复会话、管理语言，并在登录页与工作台之间切换。
 * - `Login`：提交账号密码并处理认证错误。
 * - `Workspace`：创建 Agent 运行、订阅 SSE、修正分类并处理退出。
 * - `RunPanel`：展示确定性统计、异常、交易分类与审计时间线。
 * - `LanguageSwitch`：切换中英文界面。
 *
 * 关键边界：前端不读取会话令牌；事件按序号去重，分类修正由服务端重算统计。
 */

import { FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError, api } from './api'
import { formatDate, formatMoney } from './format'
import { isPresetQuery, messages, storedLocale } from './i18n'
import type { Locale, Messages } from './i18n'
import type { Run, TransactionCategory, User } from './types'

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
      <form className="login-card" onSubmit={submit}>
        <div className="login-card-header">
          <div className="brand"><Logo /> BankPilot</div>
          <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
        </div>
        <div className="login-heading">
          <h1>{copy.loginHeading}</h1>
          <p>{copy.loginHint}</p>
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
        <button
          aria-label={submitting ? copy.loggingIn : copy.login}
          className="primary"
          disabled={submitting}
        >
          {submitting && <span className="button-spinner" aria-hidden="true" />}
          <span>{copy.login}</span>
        </button>
      </form>
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
  const [correctingId, setCorrectingId] = useState<string | null>(null)
  const eventSource = useRef<EventSource | null>(null)
  const finishingRunId = useRef<string | null>(null)

  useEffect(() => {
    setMessage((current) => (isPresetQuery(current) ? copy.defaultQuery : current))
  }, [copy])

  useEffect(() => () => {
    eventSource.current?.close()
  }, [])

  async function finishRun(runId: string) {
    if (finishingRunId.current === runId) return
    finishingRunId.current = runId
    eventSource.current?.close()
    eventSource.current = null
    try {
      setRun(await api.getRun(runId))
    } catch {
      setError(copy.queryStatusFailed)
    } finally {
      finishingRunId.current = null
      setSubmitting(false)
    }
  }

  function watchRun(runId: string) {
    eventSource.current?.close()
    eventSource.current = api.watchRunEvents(
      runId,
      (event) => {
        setRun((current) => {
          if (!current || current.events.some((item) => item.sequence === event.sequence)) {
            return current
          }
          return {
            ...current,
            events: [...current.events, event].sort((a, b) => a.sequence - b.sequence),
          }
        })
        if (event.event_type === 'run.completed' || event.event_type === 'run.failed') {
          void finishRun(runId)
        }
      },
      () => {
        // 网络断线交给 EventSource 自动重连；若会话或接口失效，则结束等待并提示。
        if (finishingRunId.current === runId) return
        void api.getRun(runId).then((current) => {
          setRun(current)
          if (terminalStatuses.has(current.status)) {
            eventSource.current?.close()
            eventSource.current = null
            setSubmitting(false)
          }
        }).catch(() => {
          eventSource.current?.close()
          setError(copy.queryStatusFailed)
          setSubmitting(false)
        })
      },
    )
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
      if (terminalStatuses.has(created.status)) {
        setSubmitting(false)
      } else {
        watchRun(created.id)
      }
    } catch {
      setError(copy.createRunFailed)
      setSubmitting(false)
    }
  }

  async function correctCategory(transactionId: string, category: TransactionCategory) {
    if (!run) return
    setError('')
    setCorrectingId(transactionId)
    try {
      setRun(await api.correctCategory(run.id, transactionId, category))
    } catch {
      setError(copy.categoryUpdateFailed)
    } finally {
      setCorrectingId(null)
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
        <form aria-busy={submitting} className="prompt" onSubmit={submit}>
          <input
            aria-label={copy.queryInputLabel}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={1000}
          />
          <button
            aria-label={submitting ? copy.querying : copy.startQuery}
            className="primary"
            disabled={submitting}
          >
            {submitting && <span className="button-spinner" aria-hidden="true" />}
            <span>{copy.startQuery}</span>
          </button>
        </form>
        <div className="suggestions">
          {copy.suggestions.map((item) => (
            <button key={item} onClick={() => setMessage(item)}>{item}</button>
          ))}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      <RunPanel
        copy={copy}
        correctingId={correctingId}
        locale={locale}
        onCategoryChange={correctCategory}
        run={run}
      />
    </main>
  )
}

function RunPanel({
  copy,
  correctingId,
  locale,
  onCategoryChange,
  run,
}: {
  copy: Messages
  correctingId: string | null
  locale: Locale
  onCategoryChange: (transactionId: string, category: TransactionCategory) => void
  run: Run | null
}) {
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
    <section className="results-grid" aria-live="polite">
      <article className="result-card">
        <div className="result-heading">
          <div><p className="eyebrow">{copy.resultEyebrow}</p><h2>{resultMessage}</h2></div>
          <Status copy={copy} status={run.status} />
        </div>
        {run.error_message && <p className="error">{run.error_code}: {run.error_message}</p>}
        {run.result && <AnalysisPanel copy={copy} locale={locale} run={run} />}
        {transactions.length > 0 && (
          <div className="transaction-list">
            {transactions.map((item) => (
              <div className="transaction" key={item.id}>
                <div className="merchant-mark">{item.merchant.slice(0, 1)}</div>
                <div className="transaction-copy">
                  <strong>{item.merchant}</strong>
                  <span>{item.description} · {formatDate(item.occurred_at, locale)}</span>
                  <select
                    aria-label={`${copy.categoryLabel}: ${item.merchant}`}
                    disabled={correctingId === item.id}
                    value={item.category}
                    onChange={(event) =>
                      onCategoryChange(item.id, event.target.value as TransactionCategory)
                    }
                  >
                    {Object.entries(copy.categoryLabels).map(([category, label]) => (
                      <option key={category} value={category}>{label}</option>
                    ))}
                  </select>
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

function AnalysisPanel({ copy, locale, run }: { copy: Messages; locale: Locale; run: Run }) {
  const analysis = run.result?.analysis
  if (!analysis) return null
  return (
    <div className="analysis-panel">
      <p className="eyebrow">{copy.analysisEyebrow}</p>
      <div className="summary-grid">
        {analysis.currency_summaries.map((summary) => (
          <div className="currency-summary" key={summary.currency}>
            <span>{summary.currency}</span>
            <dl>
              <div><dt>{copy.incomeLabel}</dt><dd className="income">{formatMoney(summary.income, summary.currency, locale)}</dd></div>
              <div><dt>{copy.expenseLabel}</dt><dd>{formatMoney(summary.expense, summary.currency, locale)}</dd></div>
              <div><dt>{copy.netLabel}</dt><dd>{formatMoney(summary.net, summary.currency, locale)}</dd></div>
            </dl>
          </div>
        ))}
      </div>
      <div className="analysis-columns">
        <section>
          <h3>{copy.categoryBreakdown}</h3>
          <div className="category-bars">
            {analysis.category_summaries.map((summary) => (
              <div className="category-row" key={`${summary.currency}-${summary.category}`}>
                <span>{copy.categoryLabels[summary.category]}</span>
                <i
                  style={{
                    width: `${categoryWidth(
                      summary.amount,
                      analysis.category_summaries
                        .filter((item) => item.currency === summary.currency)
                        .map((item) => item.amount),
                    )}%`,
                  }}
                />
                <strong>{formatMoney(summary.amount, summary.currency, locale)}</strong>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>{copy.anomalyHeading}</h3>
          {analysis.anomalies.length === 0 ? (
            <p className="muted">{copy.noAnomalies}</p>
          ) : (
            <ul className="anomaly-list">
              {analysis.anomalies.map((anomaly, index) => (
                <li className={`anomaly-${anomaly.severity}`} key={`${anomaly.rule_id}-${index}`}>
                  <span>!</span><p>{copy.anomalyDescription(anomaly)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

function categoryWidth(amount: string, amounts: string[]) {
  const maximum = Math.max(...amounts.map(Number), 1)
  return Math.max(5, Math.round((Number(amount) / maximum) * 100))
}

function Status({ copy, status }: { copy: Messages; status: Run['status'] }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>
      <i aria-hidden="true" />
      {statusLabel(status, copy)}
    </span>
  )
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
