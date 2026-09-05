/**
 * 文件职责：实现 BankPilot 登录与注册入口。
 *
 * 主要内容：切换认证模式、校验确认密码、调用认证 API 并返回当前用户。
 * 关键边界：密码只保存在组件内存中，会话令牌由 HttpOnly Cookie 管理。
 */

import { FormEvent, useState } from 'react'

import { ApiError, api } from '../../api'
import { LanguageSwitch, Logo } from '../../shared/ui'
import type { LanguageProps } from '../../shared/ui'
import type { User } from '../../types'

interface AuthPageProps extends LanguageProps {
  onAuthenticated: (user: User) => void
}

export function AuthPage({ copy, locale, onLocaleChange, onAuthenticated }: AuthPageProps) {
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
      onAuthenticated(
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
          <button type="button" aria-pressed={mode === 'login'} onClick={() => changeMode('login')}>
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
