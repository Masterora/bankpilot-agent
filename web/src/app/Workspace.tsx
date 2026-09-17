/**
 * 文件职责：组装认证后的产品工作区、共享状态与页面注册表。
 *
 * 主要内容：加载导入历史，驱动 Agent SSE 运行，协调分类修正，并渲染独立业务页面。
 * 请求归属：运行 ID 与修正请求序号共同拦截迟到响应，避免旧任务覆盖当前界面。
 * 关键边界：这里只管理跨页面状态；业务展示、解析和账务计算分别留在 feature 与服务端。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../api'
import { AssistantPanel } from '../features/assistant/AssistantPanel'
import { LedgerPage } from '../features/agent/LedgerPage'
import { AgentPage } from '../features/agent/AgentPage'
import { useAgentRun } from '../features/agent/useAgentRun'
import { AuditPage } from '../features/audit/AuditPage'
import { clearPendingImport } from '../features/imports/importRecovery'
import { ImportPage } from '../features/imports/ImportPage'
import { OverviewPage } from '../features/overview/OverviewPage'
import { RelationsPage } from '../features/relations/RelationsPage'
import { BudgetsPage } from '../features/planning/BudgetsPage'
import { RecurringPage } from '../features/planning/RecurringPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import type { RecurringInput } from '../features/planning/types'
import type { LedgerEntry } from '../features/agent/LedgerPage'
import { useWorkspaceRoute } from './routing'
import type { Messages } from '../i18n'
import { IconButton, LanguageSwitch, Logo, NavigationIcon } from '../shared/ui'
import type { LanguageProps } from '../shared/ui'
import type { ImportBatch, User } from '../types'
import { primaryPages, secondaryPages } from './pages'
import type { ProductPage } from './pages'

interface WorkspaceProps extends LanguageProps {
  user: User
  onLogout: () => void
}

export function Workspace({ copy, locale, onLocaleChange, user, onLogout }: WorkspaceProps) {
  const [drafts, setDrafts] = useState({ budgets: false, recurring: false })
  const { activePage, setActivePage, overviewPeriod, setOverviewPeriod, reviewPeriod, setReviewPeriod, budgetMonth, recurringMonth, setPlanningMonth, navigateTo } = useWorkspaceRoute(drafts)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantRevision, setAssistantRevision] = useState(0)
  const [planningRevision, setPlanningRevision] = useState(0)
  const planningSaved = useCallback(() => setPlanningRevision((value) => value + 1), [])
  const [visited, setVisited] = useState<ProductPage[]>([activePage, 'import'])
  const [recurringSeed, setRecurringSeed] = useState<RecurringInput | null>(null)
  const [relationSeed, setRelationSeed] = useState<string | undefined>()
  const [ledgerEntry, setLedgerEntry] = useState<LedgerEntry | null>(null)
  const [navigationNotice, setNavigationNotice] = useState('')
  const [focusTarget, setFocusTarget] = useState('')
  const positions = useRef<Partial<Record<ProductPage, number>>>({})
  const [menuOpen, setMenuOpen] = useState(false)
  const mobileAssistantTarget = useRef(false)
  const menuRef = useRef<HTMLButtonElement>(null)
  const navigationRef = useRef<HTMLDialogElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const previousPage = useRef<ProductPage>('overview')
  const mobileNavigationTarget = useRef<ProductPage | null>(null)
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
    if (page === 'relations') setRelationSeed(undefined)
    if (menuOpen) mobileNavigationTarget.current = page
    setMenuOpen(false)
    setFocusTarget('')
    positions.current[activePage] = window.scrollY
    setActivePage(page)
  }

  useEffect(() => {
    // 页面切换后将阅读焦点移至标题；语言切换不抢占正在编辑的输入焦点。
    setVisited((current) => current.includes(activePage) ? current : [...current, activePage])
    window.scrollTo({ top: positions.current[activePage] ?? 0 })
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
    clearPendingImport()
    // 即使远程 Cookie 已过期，也要清理本地会话界面状态。
    await api.logout().catch(() => undefined)
    onLogout()
  }

  function openPlanning(page: 'budgets' | 'recurring', month: string, target = '') {
    positions.current[activePage] = window.scrollY
    const currentMonth = page === 'budgets' ? budgetMonth : recurringMonth
    if (drafts[page] && month !== currentMonth) {
      setNavigationNotice(locale === 'en-US' ? 'Your draft is retained. Save or cancel it before changing the month.' : '已保留未保存的草稿，请先保存或取消，再查看其他月份。')
      navigate(page)
      return
    }
    setNavigationNotice('')
    setFocusTarget(target)
    navigateTo(page, month)
  }
  function inspectLedger(entry: LedgerEntry) {
    setLedgerEntry(entry)
    navigate('review')
  }
  function startRecurring(seed: RecurringInput) {
    setRecurringSeed(seed)
    openPlanning('recurring', recurringMonth)
  }

  const pages: Record<ProductPage, ReactNode> = {
    overview: (
      <OverviewPage
        copy={copy}
        english={locale === 'en-US'}
        onNavigate={(page) => { if (page === 'review') inspectLedger({ period: overviewPeriod }); else if (page === 'relations') { setRelationSeed(undefined); navigateTo(page, undefined, overviewPeriod) } else navigate(page) }}
        onPlanning={openPlanning}
        planningRevision={planningRevision}
        imports={imports}
        importsLoading={importsLoading}
        importsFailed={importsFailed}
        period={overviewPeriod}
        onPeriodChange={setOverviewPeriod}
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
        period={reviewPeriod}
        onCategoryChange={agent.correctCategory}
        onMessageChange={agent.setMessage}
        onSubmit={agent.submit}
        run={agent.run}
        submitting={agent.submitting}
      />
    ),
    import: (
      <ImportPage
        userId={user.id}
        active={activePage === 'import'}
        copy={copy}
        english={locale === 'en-US'}
        failed={importsFailed}
        imports={imports}
        loading={importsLoading}
        onAnalyze={(batch) => inspectLedger({ batchId: batch.id, period: { start: batch.start_date!, end: batch.end_date! } })}
        onReviewRelations={(batch) => { if (batch.start_date && batch.end_date) { setRelationSeed(undefined); navigateTo('relations', undefined, { start: batch.start_date, end: batch.end_date }) } }}
        onRetryHistory={() => { setImportsFailed(false); setImportsLoading(true); setImportsAttempt((value) => value + 1) }}
        onImported={(batch) => {
          setImports((current) => [batch, ...current.filter((item) => item.id !== batch.id)])
          setImportsFailed(false)

        }}
      />
    ),
    review: <LedgerPage
      active={activePage === 'review'}
      entry={ledgerEntry}
      onReviewRelation={(id) => { navigate('relations'); setRelationSeed(id) }}
      onStartRecurring={startRecurring}
      onImport={() => navigate('import')}
      onAsk={() => { agent.setMessage(`核查 ${reviewPeriod.start} 至 ${reviewPeriod.end} 的全部已导入账单`); navigate('agent') }}
      copy={copy}
      english={locale === 'en-US'}
      period={reviewPeriod}
      onPeriodChange={setReviewPeriod}
    />,
    relations: <RelationsPage onImport={() => navigate('import')} seedId={relationSeed} copy={copy} english={locale === 'en-US'} period={reviewPeriod} onPeriodChange={setReviewPeriod} />,
    reports: <ReportsPage copy={copy} locale={locale} initialMonth={reviewPeriod.start} active={activePage === 'reports'} />,
    audit: <AuditPage copy={copy} run={agent.run} locale={locale} />,
    recurring: <RecurringPage onSaved={planningSaved} copy={copy} locale={locale} month={recurringMonth} onMonthChange={setPlanningMonth} key={recurringMonth} active={activePage === 'recurring'} seed={recurringSeed} onSeedConsumed={() => setRecurringSeed(null)} onDraftChange={(dirty) => setDrafts((current) => current.recurring === dirty ? current : { ...current, recurring: dirty })} focusTarget={focusTarget} />,
    budgets: <BudgetsPage externalRevision={assistantRevision} onSaved={planningSaved} copy={copy} locale={locale} month={budgetMonth} onMonthChange={setPlanningMonth} key={budgetMonth} active={activePage === 'budgets'} focusTarget={focusTarget} onInspect={inspectLedger} onDraftChange={(dirty) => setDrafts((current) => current.budgets === dirty ? current : { ...current, budgets: dirty })} />,
  }

  return (
    <div className="product-shell">
      <aside className="product-sidebar">
        <div className="sidebar-brand brand"><Logo /> BankPilot</div>
        <Navigation
          activePage={activePage}
          copy={copy}
          onNavigate={navigate}
        />
        <div className="sidebar-utilities">
          <button onClick={() => setAssistantOpen(true)}>{locale === 'en-US' ? 'Assistant' : '问助手'}</button>
          <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
        </div>
        <div className="sidebar-account">
          <span className="account-avatar" aria-hidden="true">{user.email.slice(0, 1).toUpperCase()}</span>
          <span className="account-identity"><strong>{user.email}</strong></span>
          <IconButton icon="logout" label={copy.logout} onClick={logout} />
        </div>
      </aside>

      <dialog className="mobile-navigation" ref={navigationRef} onCancel={() => setMenuOpen(false)} onClose={() => {
        setMenuOpen(false)
        if (mobileAssistantTarget.current) {
          mobileAssistantTarget.current = false
          setAssistantOpen(true)
        } else if (mobileNavigationTarget.current) {
          const heading = contentRef.current?.querySelector<HTMLElement>('[data-active-page] h1')
          heading?.setAttribute('tabindex', '-1')
          heading?.focus({ preventScroll: true })
          mobileNavigationTarget.current = null
        } else menuRef.current?.focus()
      }} aria-label={copy.navigationLabel}>
        <div className="mobile-navigation-heading"><div className="brand"><Logo /> BankPilot</div><IconButton icon="close" onClick={() => setMenuOpen(false)} label={locale === 'en-US' ? 'Close navigation' : '关闭导航'} /></div>
        <Navigation activePage={activePage} copy={copy} onNavigate={navigate} />
        <div className="sidebar-utilities">
          <button onClick={() => { mobileAssistantTarget.current = true; setMenuOpen(false) }}>{locale === 'en-US' ? 'Assistant' : '问助手'}</button>
          <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
        </div>
        <IconButton icon="logout" label={copy.logout} onClick={logout} />
      </dialog>

      <AssistantPanel open={assistantOpen} onClose={() => setAssistantOpen(false)} month={activePage === 'budgets' ? budgetMonth : activePage === 'recurring' ? recurringMonth : activePage === 'overview' ? overviewPeriod.start : reviewPeriod.start} copy={copy} locale={locale} onSaved={() => { planningSaved(); setAssistantRevision(value => value + 1) }} />
      <main className="workspace-shell">
        <IconButton icon="menu" ref={menuRef} className="menu-toggle" onClick={() => setMenuOpen(true)} aria-expanded={menuOpen} label={locale === 'en-US' ? 'Open navigation' : '打开导航'} />

        <div className="workspace-content" ref={contentRef}>
          {navigationNotice && <p role="status">{navigationNotice}<button onClick={() => setNavigationNotice('')}>{locale === 'en-US' ? 'Dismiss' : '知道了'}</button></p>}
          {/* 已访问的编辑页面保留草稿与筛选；隐藏时暂停读取，重新进入后核对最新状态。 */}
          {(['import', 'review', 'budgets', 'recurring', 'reports'] as ProductPage[])
            .filter((page) => visited.includes(page) || page === activePage)
            .map((page) => <div key={page} hidden={activePage !== page} data-active-page={activePage === page ? '' : undefined}>{pages[page]}</div>)}
          {!['import', 'review', 'budgets', 'recurring', 'reports'].includes(activePage) && <div data-active-page="">{pages[activePage]}</div>}
          {activePage === 'review' && agent.error && <p className="error" role="alert">{agent.error}</p>}
          <footer className="workspace-footer"><span>{locale === 'en-US' ? 'Imported data · Not a bank balance' : '已导入数据 · 不代表银行余额'}</span></footer>
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
  function links(pages: ProductPage[]) {
    return pages.map((page) => <button type="button" key={page}
      className={activePage === page ? 'active' : undefined}
      aria-current={activePage === page ? 'page' : undefined} onClick={() => onNavigate(page)}>
      <NavigationIcon kind={page} /><span>{copy.productPages[page].navigation}</span>
    </button>)
  }
  return <nav className="product-nav" aria-label={copy.navigationLabel}>
    <div className="navigation-group">{links(primaryPages)}</div>
    <div className="navigation-group">
      {links(secondaryPages)}
    </div>
  </nav>
}
