/**
 * 文件职责：组装 BankPilot Web 的登录页与完整产品工作区。
 *
 * 主要内容：
 * - `App`：恢复会话、管理语言，并在登录页与工作台之间切换。
 * - `Login`：在同一认证界面完成注册或登录，并处理字段与服务端错误。
 * - `Workspace`：组装总览、Agent、导入、核查、周期扣款、预算和审计导航。
 * - 产品页：已接入的卡片、核查与审计展示真实状态，其他模块使用无数据空态。
 * - `CardPanel`：以脱敏尾号展示当前用户所属卡片。
 * - `RunPanel`：展示确定性统计、异常、交易分类与审计时间线。
 * - `LanguageSwitch`：切换中英文界面。
 *
 * 关键边界：前端不读取会话令牌；事件按序号去重，分类修正由服务端重算统计。
 */

import { FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError, api } from './api'
import { formatDate, formatMoney } from './format'
import { isPresetQuery, messages, storedLocale } from './i18n'
import type { Locale, Messages, ProductPage } from './i18n'
import type { Card, Run, TransactionCategory, User } from './types'

const terminalStatuses = new Set(['SUCCEEDED', 'FAILED', 'UNKNOWN'])
const productPages: ProductPage[] = [
  'overview',
  'agent',
  'import',
  'review',
  'recurring',
  'budgets',
  'audit',
]

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
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function changeMode(nextMode: 'login' | 'register') {
    setMode(nextMode)
    setError('')
    setPassword('')
    setPasswordConfirmation('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (mode === 'register' && password !== passwordConfirmation) {
      setError(copy.passwordMismatch)
      return
    }
    setSubmitting(true)
    try {
      onLogin(
        mode === 'register'
          ? await api.register(email, password)
          : await api.login(email, password),
      )
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setError(copy.invalidCredentials)
      } else if (mode === 'register' && reason instanceof ApiError && reason.status === 409) {
        setError(copy.emailAlreadyRegistered)
      } else {
        setError(mode === 'register' ? copy.registerFailed : copy.loginFailed)
      }
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
          <p>{mode === 'register' ? copy.registerHint : copy.loginHint}</p>
        </div>
        <div className="auth-mode-switch" role="group" aria-label={copy.loginHeading}>
          <button
            type="button"
            aria-pressed={mode === 'login'}
            onClick={() => changeMode('login')}
          >
            {copy.login}
          </button>
          <button
            type="button"
            aria-pressed={mode === 'register'}
            onClick={() => changeMode('register')}
          >
            {copy.register}
          </button>
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
            aria-label={copy.password}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={mode === 'register' ? 12 : 8}
            required
          />
          {mode === 'register' && <span className="field-hint">{copy.passwordRequirement}</span>}
        </label>
        {mode === 'register' && (
          <label>
            {copy.confirmPassword}
            <input
              type="password"
              aria-label={copy.confirmPassword}
              autoComplete="new-password"
              value={passwordConfirmation}
              onChange={(event) => setPasswordConfirmation(event.target.value)}
              minLength={12}
              required
            />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button
          aria-label={
            submitting
              ? mode === 'register' ? copy.registering : copy.loggingIn
              : mode === 'register' ? copy.register : copy.login
          }
          className="primary"
          disabled={submitting}
        >
          {submitting && <span className="button-spinner" aria-hidden="true" />}
          <span>{mode === 'register' ? copy.register : copy.login}</span>
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
  const [activePage, setActivePage] = useState<ProductPage>('overview')
  const [message, setMessage] = useState(copy.defaultQuery)
  const [cards, setCards] = useState<Card[]>([])
  const [cardsLoading, setCardsLoading] = useState(true)
  const [cardsFailed, setCardsFailed] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [correctingId, setCorrectingId] = useState<string | null>(null)
  const eventSource = useRef<EventSource | null>(null)
  const finishingRunId = useRef<string | null>(null)

  useEffect(() => {
    setMessage((current) => (isPresetQuery(current) ? copy.defaultQuery : current))
  }, [copy])

  useEffect(() => {
    let active = true
    api.listCards()
      .then((response) => {
        if (active) setCards(response.items)
      })
      .catch(() => {
        if (active) setCardsFailed(true)
      })
      .finally(() => {
        if (active) setCardsLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

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
    <div className="product-shell">
      <aside className="product-sidebar">
        <div className="sidebar-brand brand"><Logo /> BankPilot</div>
        <p className="sidebar-label">{copy.navigationLabel}</p>
        <nav className="product-nav" aria-label={copy.navigationLabel}>
          {productPages.map((page) => (
            <button
              type="button"
              className={activePage === page ? 'active' : undefined}
              aria-current={activePage === page ? 'page' : undefined}
              key={page}
              onClick={() => setActivePage(page)}
            >
              <NavigationIcon kind={page} />
              <span>{copy.productPages[page].navigation}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-account">
          <span>{user.email}</span>
          <button onClick={logout}>{copy.logout}</button>
        </div>
      </aside>

      <main className="workspace-shell">
        <header className="workspace-topbar">
          <div className="topbar-brand brand"><Logo /> BankPilot</div>
          <div className="topbar-context">
            <strong>{copy.productPages[activePage].navigation}</strong>
            <span><i aria-hidden="true" />{copy.readOnlyScope}</span>
          </div>
          <div className="header-actions">
            <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
            <div className="account-chip">
              <span>{user.email}</span>
              <button onClick={logout}>{copy.logout}</button>
            </div>
          </div>
        </header>

        <div className="workspace-content">
          {activePage === 'overview' && (
            <OverviewPage
              cards={cards}
              cardsFailed={cardsFailed}
              cardsLoading={cardsLoading}
              copy={copy}
              onNavigate={setActivePage}
              run={run}
            />
          )}
          {activePage === 'agent' && (
            <AgentPage
              copy={copy}
              correctingId={correctingId}
              error={error}
              locale={locale}
              message={message}
              onCategoryChange={correctCategory}
              onMessageChange={setMessage}
              onSubmit={submit}
              run={run}
              submitting={submitting}
            />
          )}
          {activePage === 'review' && (
            <ReviewPage
              copy={copy}
              correctingId={correctingId}
              locale={locale}
              onCategoryChange={correctCategory}
              run={run}
            />
          )}
          {activePage === 'audit' && <AuditPage copy={copy} run={run} />}
          {(activePage === 'import' || activePage === 'recurring' || activePage === 'budgets') && (
            <EmptyProductPage copy={copy} page={activePage} />
          )}
        </div>
      </main>
    </div>
  )
}

function PageHeader({ copy, page }: { copy: Messages; page: ProductPage }) {
  const content = copy.productPages[page]
  return (
    <header className="page-header">
      <p className="eyebrow">{content.eyebrow}</p>
      <h1>{content.title}</h1>
      <p>{content.description}</p>
    </header>
  )
}

function OverviewPage({
  cards,
  cardsFailed,
  cardsLoading,
  copy,
  onNavigate,
  run,
}: {
  cards: Card[]
  cardsFailed: boolean
  cardsLoading: boolean
  copy: Messages
  onNavigate: (page: ProductPage) => void
  run: Run | null
}) {
  const transactionCount = run?.result?.transactions.items.length ?? 0
  const signalCount = run?.result?.analysis.anomalies.length ?? 0
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="overview" />
      <div className="overview-metrics">
        <Metric label={copy.linkedCardsMetric} value={cardsLoading ? '—' : String(cards.length)} />
        <Metric label={copy.transactionsMetric} value={String(transactionCount)} />
        <Metric label={copy.reviewSignalsMetric} value={String(signalCount)} />
        <Metric
          label={copy.latestRunMetric}
          value={run ? copy.statuses[run.status] : copy.noRunStatus}
        />
      </div>
      <section className="quick-tasks">
        <div>
          <p className="eyebrow">Agent</p>
          <h2>{copy.quickTasksHeading}</h2>
        </div>
        <div className="quick-task-actions">
          <button type="button" onClick={() => onNavigate('agent')}>
            <NavigationIcon kind="agent" />
            <span>{copy.openAgent}</span>
          </button>
          <button type="button" onClick={() => onNavigate('review')}>
            <NavigationIcon kind="review" />
            <span>{copy.openReview}</span>
          </button>
        </div>
      </section>
      <CardPanel cards={cards} copy={copy} failed={cardsFailed} loading={cardsLoading} />
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <article className="overview-metric"><span>{label}</span><strong>{value}</strong></article>
}

function AgentPage({
  copy,
  correctingId,
  error,
  locale,
  message,
  onCategoryChange,
  onMessageChange,
  onSubmit,
  run,
  submitting,
}: {
  copy: Messages
  correctingId: string | null
  error: string
  locale: Locale
  message: string
  onCategoryChange: (transactionId: string, category: TransactionCategory) => void
  onMessageChange: (message: string) => void
  onSubmit: (event: FormEvent) => void
  run: Run | null
  submitting: boolean
}) {
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="agent" />
      <section className="agent-command">
        <form aria-busy={submitting} className="prompt" onSubmit={onSubmit}>
          <input
            aria-label={copy.queryInputLabel}
            value={message}
            onChange={(event) => onMessageChange(event.target.value)}
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
            <button type="button" key={item} onClick={() => onMessageChange(item)}>{item}</button>
          ))}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      <RunPanel
        copy={copy}
        correctingId={correctingId}
        locale={locale}
        onCategoryChange={onCategoryChange}
        run={run}
      />
    </section>
  )
}

function ReviewPage({
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
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="review" />
      <RunPanel
        copy={copy}
        correctingId={correctingId}
        locale={locale}
        onCategoryChange={onCategoryChange}
        run={run}
      />
    </section>
  )
}

function EmptyProductPage({ copy, page }: { copy: Messages; page: ProductPage }) {
  return (
    <section className="product-page">
      <PageHeader copy={copy} page={page} />
      <section className="module-empty"><NavigationIcon kind={page} /><p>{copy.productPages[page].empty}</p></section>
    </section>
  )
}

function AuditPage({ copy, run }: { copy: Messages; run: Run | null }) {
  const boundaries = [
    [copy.sourceDataBoundary, copy.sourceDataBoundaryDetail],
    [copy.modelBoundary, copy.modelBoundaryDetail],
    [copy.accountBoundary, copy.accountBoundaryDetail],
    [copy.secretBoundary, copy.secretBoundaryDetail],
  ]
  return (
    <section className="product-page">
      <PageHeader copy={copy} page="audit" />
      <div className="audit-grid">
        <article className="audit-panel">
          <p className="eyebrow">{copy.auditBoundaryHeading}</p>
          <div className="boundary-list">
            {boundaries.map(([title, detail]) => (
              <div className="boundary-item" key={title}>
                <span aria-hidden="true" />
                <div><strong>{title}</strong><p>{detail}</p></div>
              </div>
            ))}
          </div>
        </article>
        <article className="audit-panel">
          <p className="eyebrow">{copy.auditEventsHeading}</p>
          {run?.events.length ? (
            <ol className="audit-events">
              {run.events.map((event) => (
                <li key={event.sequence}><span />{eventLabel(event.event_type, copy)}</li>
              ))}
            </ol>
          ) : <p className="module-empty-copy">{copy.productPages.audit.empty}</p>}
        </article>
      </div>
    </section>
  )
}

function CardPanel({
  cards,
  copy,
  failed,
  loading,
}: {
  cards: Card[]
  copy: Messages
  failed: boolean
  loading: boolean
}) {
  return (
    <section className="cards-section" aria-live="polite">
      <div className="cards-heading">
        <p className="eyebrow">{copy.cardsEyebrow}</p>
        <h2>{copy.cardsHeading}</h2>
      </div>
      {loading ? (
        <p className="cards-message">{copy.cardsLoading}</p>
      ) : failed ? (
        <p className="error" role="alert">{copy.cardsLoadFailed}</p>
      ) : cards.length === 0 ? (
        <p className="cards-message">{copy.cardsEmpty}</p>
      ) : (
        <div className="card-list">
          {cards.map((card) => (
            <article className="bank-card" key={card.id}>
              <div className="bank-card-header">
                <strong>{card.display_name}</strong>
                <span className={`card-status card-status-${card.status.toLowerCase()}`}>
                  {copy.cardStatuses[card.status]}
                </span>
              </div>
              <p><span>••••</span> {card.last_four}</p>
              <div className="bank-card-footer">
                <span>{card.account_name}</span>
                <span>{copy.cardEnding} {card.last_four}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
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
    return <section className="empty-state"><p>{copy.emptyResult}</p></section>
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
  // 页面品牌标识与浏览器 favicon 复用同一资产，避免不同入口出现两套视觉语言。
  return <img className="logo" src="/bankpilot-mark.svg?v=2" alt="" aria-hidden="true" />
}

function NavigationIcon({ kind }: { kind: ProductPage }) {
  const paths = {
    overview: <><path d="m4 11 8-7 8 7v9h-5v-6H9v6H4Z" /></>,
    agent: <><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5Z" /><path d="m18.5 16 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7Z" /></>,
    import: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 15v5h16v-5" /></>,
    review: <><path d="M5 20V10m7 10V4m7 16v-7" /><path d="M3 20h18" /></>,
    recurring: <><path d="m17 3 4 4-4 4" /><path d="M3 12V9a2 2 0 0 1 2-2h16" /><path d="m7 21-4-4 4-4" /><path d="M21 12v3a2 2 0 0 1-2 2H3" /></>,
    budgets: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
    audit: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>
}

function LoadingScreen({ label }: { label: string }) {
  return <main className="loading-screen"><Logo /><p>{label}</p></main>
}
