/**
 * 文件职责：实现 BankPilot 登录与注册入口。
 *
 * 主要内容：切换认证模式、校验确认密码、调用认证 API 并返回当前用户。
 * 关键边界：密码只保存在组件内存中，会话令牌由 HttpOnly Cookie 管理。
 */

import { FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../../api'
import { Logo } from '../../shared/ui'
import type { LanguageProps } from '../../shared/ui'
import type { User } from '../../types'

const MIN_PASSWORD_LENGTH = 8
const validNewPassword = (value: string) =>
  /[a-z]/.test(value)
  && /[A-Z]/.test(value)
  && /[0-9]/.test(value)
  && /[^A-Za-z0-9\s]/.test(value)

interface AuthPageProps extends LanguageProps {
  switchingAccount?: boolean
  onAuthenticated: (user: User) => void
}

export function AuthPage({ copy, locale, onAuthenticated, switchingAccount = false }: AuthPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const confirmationRef = useRef<HTMLInputElement>(null)
  const [confirmationError, setConfirmationError] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    document.title = `${mode === 'register' ? copy.register : switchingAccount ? (locale === 'en-US' ? 'Switch account' : '切换账号') : copy.login} · BankPilot`
  }, [mode, copy, locale, switchingAccount])

  function changeMode(nextMode: 'login' | 'register') {
    if (submitting || nextMode === mode) return
    setMode(nextMode)
    setError('')
    setConfirmationError('')
    setPassword('')
    setPasswordConfirmation('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setConfirmationError('')
    if (mode === 'register' && !validNewPassword(password)) {
      setError(copy.passwordFormatInvalid)
      return
    }
    if (mode === 'register' && password !== passwordConfirmation) {
      setConfirmationError(copy.passwordMismatch)
      confirmationRef.current?.focus()
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
        </div>
        <div className="login-heading">
          <h1>{mode === 'register' ? (locale === 'en-US' ? 'Create your account' : '创建账户') : switchingAccount ? (locale === 'en-US' ? 'Sign in to another account' : '登录其他账号') : copy.login}</h1>
        </div>
        <div className="auth-mode-switch" role="group" aria-label={copy.loginHeading}>
          <button type="button" disabled={submitting} aria-pressed={mode === 'login'} onClick={() => changeMode('login')}>
            {copy.login}
          </button>
          <button
            type="button"
            disabled={submitting}
            aria-pressed={mode === 'register'}
            onClick={() => changeMode('register')}
          >
            {copy.register}
          </button>
        </div>
        <label>
          {copy.email}
          <input
            disabled={submitting}
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
            disabled={submitting}
            type="password"
            aria-label={copy.password}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={128}
            pattern={mode === 'register' ? '(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])(?=.*[^A-Za-z0-9\\s]).{8,128}' : undefined}
            required
          />
          {mode === 'register' && <span className="field-hint">{copy.passwordRequirement}</span>}
        </label>
        {mode === 'register' && (
          <label>
            {copy.confirmPassword}
            <input
              ref={confirmationRef}
              disabled={submitting}
              type="password"
              aria-invalid={Boolean(confirmationError)}
              aria-describedby={confirmationError ? 'confirmation-error' : undefined}
              aria-label={copy.confirmPassword}
              autoComplete="new-password"
              value={passwordConfirmation}
              onChange={(event) => { setPasswordConfirmation(event.target.value); setConfirmationError('') }}
              minLength={MIN_PASSWORD_LENGTH}
              maxLength={128}
              required
            />
            {confirmationError && <span id="confirmation-error" className="error" role="alert">{confirmationError}</span>}
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
          aria-busy={submitting}
        >
          {submitting && <span className="button-spinner" aria-hidden="true" />}
          <span>{mode === 'register' ? copy.register : copy.login}</span>
        </button>
      </form>
    </main>
  )
}
