/**
 * 文件职责：组装认证后的产品工作区、共享状态与页面注册表。
 *
 * 主要内容：加载导入历史，驱动 Agent SSE 运行，协调分类修正，并渲染独立业务页面。
 * 请求归属：运行 ID 与修正请求序号共同拦截迟到响应，避免旧任务覆盖当前界面。
 * 关键边界：这里只管理跨页面状态；业务展示、解析和账务计算分别留在 feature 与服务端。
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../api'
import { LedgerPage } from '../features/agent/LedgerPage'
import { AgentPage } from '../features/agent/AgentPage'
import { useAgentRun } from '../features/agent/useAgentRun'
import { AuditPage } from '../features/audit/AuditPage'
import { ImportPage } from '../features/imports/ImportPage'
import { OverviewPage } from '../features/overview/OverviewPage'
import { RelationsPage } from '../features/relations/RelationsPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import { useWorkspaceRoute } from './routing'
import type { Messages } from '../i18n'
import { EmptyProductPage, LanguageSwitch, Logo, NavigationIcon } from '../shared/ui'
import type { LanguageProps } from '../shared/ui'
import type { ImportBatch, User } from '../types'
import { navigationGroups } from './pages'
import type { ProductPage } from './pages'

interface WorkspaceProps extends LanguageProps {
  user: User
  onLogout: () => void
}

export function Workspace({ copy, locale, onLocaleChange, user, onLogout }: WorkspaceProps) {
  const { activePage, setActivePage, reviewPeriod, setReviewPeriod } = useWorkspaceRoute()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLButtonElement>(null)
  const navigationRef = useRef<HTMLDialogElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const previousPage = useRef<ProductPage>('overview')
  const agent = useAgentRun(copy)
  const [imports, setImports] = useState<ImportBatch[]>([])
  const [importsLoading, setImportsLoading] = useState(true)
  const [importsFailed, setImportsFailed] = useState(false)
  const [importsAttempt, setImportsAttempt] = useState(0)

  // 原生模态导航提供焦点约束与 Escape 关闭；桌面导航不参与模态状态。
  useEffect(() => {
    if (menuOpen) navigationRef.current?.showModal()
    else navigationRef.current?.close()
  }, [menuOpen])

  function navigate(page: ProductPage) {
    setMenuOpen(false)
    setActivePage(page)
    window.scrollTo({ top: 0 })
  }

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
  }, [importsAttempt])

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
        onNavigate={navigate}
        period={reviewPeriod}
        onPeriodChange={setReviewPeriod}
      />
    ),
    agent: (
      <AgentPage
        correctionSaved={agent.correctionSaved}
        copy={copy}
        correctingId={agent.correctingId}
        error={agent.error}
        locale={locale}
        message={agent.message}
        onCategoryChange={agent.correctCategory}
        onMessageChange={agent.setMessage}
        onSubmit={agent.submit}
        run={agent.run}
        submitting={agent.submitting}
      />
    ),
    import: (
      <ImportPage
        active={activePage === 'import'}
        copy={copy}
        english={locale === 'en-US'}
        failed={importsFailed}
        imports={imports}
        loading={importsLoading}
        onAnalyze={() => setActivePage('review')}
        onRetryHistory={() => { setImportsFailed(false); setImportsLoading(true); setImportsAttempt((value) => value + 1) }}
        onImported={(batch) => {
          setImports((current) => [batch, ...current.filter((item) => item.id !== batch.id)])
          setImportsFailed(false)
          if (batch.start_date && batch.end_date) {
            setReviewPeriod({ start: batch.start_date, end: batch.end_date })
          }
        }}
      />
    ),
    review: <LedgerPage
      copy={copy}
      english={locale === 'en-US'}
      period={reviewPeriod}
      onPeriodChange={setReviewPeriod}
    />,
    relations: <RelationsPage copy={copy} english={locale === 'en-US'} period={reviewPeriod} onPeriodChange={setReviewPeriod} />,
    reports: <ReportsPage copy={copy} locale={locale} initialMonth={reviewPeriod.start} />,
    audit: <AuditPage copy={copy} run={agent.run} locale={locale} />,
    recurring: <EmptyProductPage copy={copy} page="recurring" />,
    budgets: <EmptyProductPage copy={copy} page="budgets" />,
  }

  return (
    <div className="product-shell">
      <aside className="product-sidebar">
        <div className="sidebar-brand brand"><Logo /> BankPilot</div>
        <Navigation
          activePage={activePage}
          copy={copy}
          english={locale === 'en-US'}
          onNavigate={navigate}
        />
        <div className="sidebar-account">
          <span className="account-avatar" aria-hidden="true">{user.email.slice(0, 1).toUpperCase()}</span>
          <span className="account-identity"><strong>{user.email}</strong><small>{locale === 'en-US' ? 'Workspace connected' : '工作区已连接'}</small></span>
          <button onClick={logout}>{copy.logout}</button>
        </div>
      </aside>

      <dialog className="mobile-navigation" ref={navigationRef} onCancel={() => setMenuOpen(false)} onClose={() => { setMenuOpen(false); menuRef.current?.focus() }} aria-label={copy.navigationLabel}>
        <div className="mobile-navigation-heading"><div className="brand"><Logo /> BankPilot</div><button type="button" onClick={() => setMenuOpen(false)} aria-label={locale === 'en-US' ? 'Close navigation' : '关闭导航'}>×</button></div>
        <Navigation activePage={activePage} copy={copy} english={locale === 'en-US'} onNavigate={navigate} />
      </dialog>

      <main className="workspace-shell">
        <header className="workspace-topbar">
          <button ref={menuRef} type="button" className="menu-toggle" onClick={() => setMenuOpen(true)} aria-expanded={menuOpen} aria-label={locale === 'en-US' ? 'Open navigation' : '打开导航'}>☰</button>
          <div className="workspace-breadcrumb"><small>{locale === 'en-US' ? 'Personal ledger' : '个人账本'}</small><strong>{copy.productPages[activePage].title}</strong></div>
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
          {activePage === 'review' && agent.error && <p className="error" role="alert">{agent.error}</p>}
          <footer className="workspace-footer"><span>{locale === 'en-US' ? 'Imported data · Not a bank balance' : '已导入数据 · 不代表银行余额'}</span><span>UTC+08:00</span></footer>
        </div>
      </main>
    </div>
  )
}

function Navigation({
  activePage,
  copy,
  english,
  onNavigate,
}: {
  activePage: ProductPage
  copy: Messages
  english: boolean
  onNavigate: (page: ProductPage) => void
}) {
  const groupLabels = english
    ? { ledger: 'Ledger', analysis: 'Review & control', planning: 'Planning' }
    : { ledger: '账务管理', analysis: '核查与治理', planning: '分析规划' }
  return (
    <nav className="product-nav" aria-label={copy.navigationLabel}>
      {navigationGroups.map((group) => <div className="navigation-group" key={group.id}>
      <p className="navigation-group-label">{groupLabels[group.id as keyof typeof groupLabels]}</p>
      {group.pages.map((page) => (
        <button
          type="button"
          className={activePage === page ? 'active' : undefined}
          aria-current={activePage === page ? 'page' : undefined}
          key={page}
          onClick={() => onNavigate(page)}
        >
          <NavigationIcon kind={page} />
          <span>{copy.productPages[page].navigation}</span>
          {(page === 'recurring' || page === 'budgets') && <small>{english ? 'Planned' : '规划中'}</small>}
        </button>
      ))}
      </div>)}
    </nav>
  )
}
