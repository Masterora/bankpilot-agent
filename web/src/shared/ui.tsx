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
      <p className="eyebrow">{content.eyebrow}</p>
      <h1>{content.title}</h1>
      <p>{content.description}</p>
    </header>
  )
}

export function Logo() {
  // 页面品牌标识与浏览器 favicon 复用同一资产，避免不同入口出现两套视觉语言。
  return <img className="logo" src="/bankpilot-mark.svg?v=2" alt="" aria-hidden="true" />
}

/** 保留未接入数据的产品页面结构，不模拟结果或执行操作。 */
export function EmptyProductPage({ copy, page }: { copy: Messages; page: ProductPage }) {
  return <section className="product-page"><PageHeader copy={copy} page={page} /><section className="module-empty"><NavigationIcon kind={page} /><p>{copy.productPages[page].empty}</p></section></section>
}

export function NavigationIcon({ kind }: { kind: ProductPage }) {
  const paths: Record<ProductPage, ReactNode> = {
    overview: <path d="m4 11 8-7 8 7v9h-5v-6H9v6H4Z" />,
    recurring: <><path d="m17 3 4 4-4 4" /><path d="M3 12V9a2 2 0 0 1 2-2h16" /><path d="m7 21-4-4 4-4" /><path d="M21 12v3a2 2 0 0 1-2 2H3" /></>,
    budgets: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
    agent: <><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5Z" /><path d="m18.5 16 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7Z" /></>,
    import: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 15v5h16v-5" /></>,
    review: <><path d="M5 20V10m7 10V4m7 16v-7" /><path d="M3 20h18" /></>,
    audit: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>
}

export function LoadingScreen({ label }: { label: string }) {
  return <main className="loading-screen"><Logo /><p>{label}</p></main>
}
