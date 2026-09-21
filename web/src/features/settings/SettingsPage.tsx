/**
 * 文件职责：展示当前账户与本地显示偏好设置。
 * 主要内容：账户信息、切换账号与退出、语言偏好，以及密码修改表单。
 * 关键边界：只提供已接入的操作，身份与密码校验由服务端完成。
 */
import type { LanguageProps } from '../../shared/ui'
import { LanguageSwitch, PageHeader } from '../../shared/ui'
import { PasswordForm } from './PasswordForm'
import type { User } from '../../types'

export function SettingsPage({ copy, locale, onLocaleChange, user, onLogout, onSwitchAccount, busy }: LanguageProps & {
  user: User
  onLogout: () => void
  onSwitchAccount: () => void
  busy: boolean
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
            </div>
          </div>
          <details className="inline-note"><summary>{en ? 'Sign-out details' : '退出说明'}</summary><p>{en ? 'Signing out clears local recovery data. Saved conversations remain in your history.' : '退出会清除本地恢复记录，已保存的对话仍可在历史中找回。'}</p></details>
          <div className="settings-row"><button disabled={busy} onClick={onSwitchAccount}>{en ? 'Switch account' : '切换账号'}</button><button disabled={busy} onClick={onLogout}>{copy.logout}</button></div>
        </section>
        <section className="settings-card">
          <h2>{en ? 'Language' : '语言'}</h2>
          <div className="settings-row">
            <LanguageSwitch copy={copy} locale={locale} onLocaleChange={onLocaleChange} />
          </div>
        </section>
        <PasswordForm copy={copy} locale={locale} />
      </div>
    </section>
  )
}
