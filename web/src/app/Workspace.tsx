/**
 * 文件职责：组装认证后的产品工作区、共享状态与页面注册表。
 *
 * 主要内容：加载导入历史，驱动 Agent SSE 运行，协调分类修正，并渲染独立业务页面。
 * 关键边界：这里只管理跨页面状态；业务展示、解析和账务计算分别留在 feature 与服务端。
 */

import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

import { api } from '../api'
import { LedgerPage } from '../features/agent/LedgerPage'
import { AgentPage } from '../features/agent/AgentPage'
import { AuditPage } from '../features/audit/AuditPage'
import { ImportPage } from '../features/imports/ImportPage'
import { OverviewPage } from '../features/overview/OverviewPage'
import { isPresetQuery } from '../i18n'
import type { Messages } from '../i18n'
import { EmptyProductPage, LanguageSwitch, Logo, NavigationIcon } from '../shared/ui'
import type { LanguageProps } from '../shared/ui'
import type { ImportBatch, Run, TransactionCategory, User } from '../types'
import { pageDefinitions } from './pages'
import type { ProductPage } from './pages'

const terminalStatuses = new Set(['SUCCEEDED', 'FAILED', 'UNKNOWN'])

interface WorkspaceProps extends LanguageProps {
  user: User
  onLogout: () => void
}

export function Workspace({ copy, locale, onLocaleChange, user, onLogout }: WorkspaceProps) {
  const [activePage, setActivePage] = useState<ProductPage>('overview')
  const contentRef = useRef<HTMLDivElement>(null)
  const previousPage = useRef<ProductPage>('overview')
  const [message, setMessage] = useState(copy.defaultQuery)
  const [imports, setImports] = useState<ImportBatch[]>([])
  const [importsLoading, setImportsLoading] = useState(true)
  const [importsFailed, setImportsFailed] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [correctingId, setCorrectingId] = useState<string | null>(null)
  const eventSource = useRef<EventSource | null>(null)
  const finishingRunId = useRef<string | null>(null)

  useEffect(() => {
    // 页面切换后将阅读焦点移至标题；语言切换不抢占正在编辑的输入焦点。
    document.title = `${copy.productPages[activePage].title} · BankPilot`
    if (previousPage.current !== activePage) {
      const heading = contentRef.current?.querySelector<HTMLElement>('[data-active-page] h1')
      heading?.setAttribute('tabindex', '-1')
      heading?.focus({ preventScroll: true })
      previousPage.current = activePage
    }
  }, [activePage, copy])

  useEffect(() => {
    setMessage((current) => (isPresetQuery(current) ? copy.defaultQuery : current))
  }, [copy])


  useEffect(() => {
    let active = true
    api.listImports()
      .then((response) => {
        if (active) setImports(response.items)
      })
      .catch(() => {
        if (active) setImportsFailed(true)
      })
      .finally(() => {
        if (active) setImportsLoading(false)
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
        // 网络断线交给 EventSource 自动重连；会话或接口失效时结束等待并提示。
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !message.trim()) return
    setError('')
    setRun(null)
    setSubmitting(true)
    try {
      const created = await api.createRun(message.trim())
      setRun(created)
      if (terminalStatuses.has(created.status)) setSubmitting(false)
      else watchRun(created.id)
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

  const pages: Record<ProductPage, ReactNode> = {
    overview: (
      <OverviewPage
        copy={copy}
        english={locale === 'en-US'}
        onNavigate={setActivePage}
        run={run}
      />
    ),
    agent: (
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
    ),
    import: (
      <ImportPage
        copy={copy}
        english={locale === 'en-US'}
        failed={importsFailed}
        imports={imports}
        loading={importsLoading}
        onAnalyze={() => setActivePage('agent')}
        onImported={(batch) => {
          setImports((current) => [batch, ...current.filter((item) => item.id !== batch.id)])
          setImportsFailed(false)
        }}
      />
    ),
    review: <LedgerPage copy={copy} english={locale === 'en-US'} />,
    audit: <AuditPage copy={copy} run={run} />,
    recurring: <EmptyProductPage copy={copy} page="recurring" />,
    budgets: <EmptyProductPage copy={copy} page="budgets" />,
  }

  return (
    <div className="product-shell">
      <aside className="product-sidebar">
        <div className="sidebar-brand brand"><Logo /> BankPilot</div>
        <p className="sidebar-label">{copy.navigationLabel}</p>
        <Navigation
          activePage={activePage}
          copy={copy}
          onNavigate={setActivePage}
        />
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
            <span>
              <i aria-hidden="true" />
              {pageDefinitions.find((page) => page.id === activePage)?.scope === 'write'
                ? copy.localDataScope
                : copy.readOnlyScope}
            </span>
          </div>
          <div className="header-actions">
            <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
            <div className="account-chip">
              <span>{user.email}</span>
              <button onClick={logout}>{copy.logout}</button>
            </div>
          </div>
        </header>

        <div className="workspace-content" ref={contentRef}>
          {/* 导入表单保持挂载，切换页面不会丢失已选文件与字段映射。 */}
          <div hidden={activePage !== 'import'} data-active-page={activePage === 'import' ? '' : undefined}>{pages.import}</div>
          {activePage !== 'import' && <div data-active-page="">{pages[activePage]}</div>}
          {activePage === 'review' && error && <p className="error" role="alert">{error}</p>}
        </div>
      </main>
    </div>
  )
}

function Navigation({
  activePage,
  copy,
  onNavigate,
}: {
  activePage: ProductPage
  copy: Messages
  onNavigate: (page: ProductPage) => void
}) {
  return (
    <nav className="product-nav" aria-label={copy.navigationLabel}>
      {pageDefinitions.map((page) => (
        <button
          type="button"
          className={activePage === page.id ? 'active' : undefined}
          aria-current={activePage === page.id ? 'page' : undefined}
          key={page.id}
          onClick={() => onNavigate(page.id)}
        >
          <NavigationIcon kind={page.id} />
          <span>{copy.productPages[page.id].navigation}</span>
        </button>
      ))}
    </nav>
  )
}
