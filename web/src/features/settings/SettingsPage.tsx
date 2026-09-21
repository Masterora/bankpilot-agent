/** 账户与本地显示偏好；仅提供当前已接入的操作。 */
import type { LanguageProps } from '../../shared/ui'
import { LanguageSwitch, PageHeader } from '../../shared/ui'
import type { User } from '../../types'

export function SettingsPage({ copy, locale, onLocaleChange, user, onLogout }: LanguageProps & {
  user: User
  onLogout: () => void
}) {
  const en = locale === 'en-US'
  return (
    <section className="product-page settings-page">
      <PageHeader copy={copy} page="settings" />
      <div className="settings-grid">
        <section className="settings-card">
          <h2>{en ? 'Your account' : '个人账户'}</h2>
          <div className="settings-profile">
            <span className="account-avatar">{user.email.slice(0, 1).toUpperCase()}</span>
            <div>
              <strong>{user.email}</strong>
              <p>{en ? 'Personal workspace' : '个人工作区'}</p>
            </div>
          </div>
        </section>
        <section className="settings-card">
          <h2>{en ? 'Appearance' : '外观'}</h2>
          <div className="settings-row">
            <span>{en ? 'Current theme' : '当前主题'}</span>
            <span className="theme-badge">{en ? 'Dark · Teal' : '深色 · 青绿'}</span>
          </div>
        </section>
        <section className="settings-card">
          <h2>{en ? 'Language' : '语言'}</h2>
          <div className="settings-row">
            <span>{en ? 'Display language' : '界面语言'}</span>
            <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
          </div>
          <p>{en ? 'Saved in this browser.' : '偏好保存在当前浏览器。'}</p>
        </section>
        <section className="settings-card">
          <h2>{en ? 'Session' : '登录状态'}</h2>
          <p>{en ? 'Signing out clears this conversation.' : '退出将清空当前助手对话。'}</p>
          <button onClick={onLogout}>{copy.logout}</button>
        </section>
        <section className="settings-card">
          <h2>{en ? 'Data' : '数据说明'}</h2>
          <p>{en ? 'Totals cover imported statements, not bank balances.' : '统计仅含导入账单，不代表银行余额。'}</p>
        </section>
      </div>
    </section>
  )
}
