/**
 * 文件职责：提供跨业务页面复用的品牌、语言、标题、导航图标与加载组件。
 *
 * 主要内容：`Logo`、`LanguageSwitch`、`PageHeader`、`NavigationIcon` 和 `LoadingScreen`。
 * 关键边界：共享组件只负责显示和回调，不读取业务数据或调用 API。
 */

import type { ReactNode } from 'react'

import type { Locale, Messages, ProductPage } from '../i18n'

export interface LanguageProps {
  copy: Messages
  locale: Locale
  onLocaleChange: (locale: Locale) => void
}

export function LanguageSwitch({ copy, locale, onLocaleChange }: LanguageProps) {
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

export function PageHeader({ copy, page }: { copy: Messages; page: ProductPage }) {
  const content = copy.productPages[page]
  return (
    <header className="page-header">
      <h1>{content.title}</h1>
    </header>
  )
}

export function Logo() {
  // 页面品牌标识与浏览器 favicon 复用同一资产，避免不同入口出现两套视觉语言。
  return <img className="logo" src="/bankpilot-mark.svg?v=3" alt="" aria-hidden="true" />
}

/** 空数据保留功能轮廓与下一步操作，不用占位数字冒充真实统计。 */
export function EmptyContent({ title, detail, kind, children }: {
  title: string; detail: string; kind: ProductPage; children?: ReactNode
}) {
  return <div className="empty-content"><span className="empty-content-icon" aria-hidden="true"><NavigationIcon kind={kind} /></span><h3>{title}</h3><p>{detail}</p>{children && <div className="empty-content-actions">{children}</div>}</div>
}

/** 保留未接入数据的产品页面结构，不模拟结果或执行操作。 */
export function EmptyProductPage({ copy, page }: { copy: Messages; page: ProductPage }) {
  return <section className="product-page"><PageHeader copy={copy} page={page} /><section className="module-empty"><NavigationIcon kind={page} /><h2>{copy.productPages[page].navigation}</h2><p>{copy.productPages[page].empty}</p></section></section>
}

export function NavigationIcon({ kind }: { kind: ProductPage }) {
  const paths: Record<ProductPage, ReactNode> = {
    overview: <path d="m4 11 8-7 8 7v9h-5v-6H9v6H4Z" />,
    relations: <><path d="M10 7H7a5 5 0 0 0 0 10h3m4-10h3a5 5 0 0 1 0 10h-3M8 12h8" /></>,
    reports: <><path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h5" /></>,
    recurring: <><path d="m17 3 4 4-4 4" /><path d="M3 12V9a2 2 0 0 1 2-2h16" /><path d="m7 21-4-4 4-4" /><path d="M21 12v3a2 2 0 0 1-2 2H3" /></>,
    budgets: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
    agent: <><path d="M4 5h16v12H9l-5 4zM8 9h8M8 13h5" /></>,
    import: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 15v5h16v-5" /></>,
    review: <path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5" />,
    audit: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>
}

export function LoadingScreen({ label }: { label: string }) {
  return <main className="loading-screen"><Logo /><p>{label}</p></main>
}
