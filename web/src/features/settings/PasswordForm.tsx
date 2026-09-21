import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../../api'
import type { LanguageProps } from '../../shared/ui'

export function PasswordForm({ copy, locale }: Pick<LanguageProps, 'copy' | 'locale'>) {
  const en = locale === 'en-US'
  const [open, setOpen] = useState(false)
  const [next, setNext] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [field, setField] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  function clear() { setNext(''); setConfirmation(''); setError(''); setField('') }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError(''); setField(''); setSaved(false)
    if (next !== confirmation) { setField('confirmation'); setError(copy.passwordMismatch); return }
    setBusy(true)
    try {
      await api.changePassword(next)
      clear(); setOpen(false); setSaved(true)
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'password_unchanged') {
        setField('next'); setError(en ? 'Choose a different new password.' : '新密码不能与当前密码相同。')
      } else if (cause instanceof ApiError && cause.status === 401) {
        setError(en ? 'Session expired. Sign in again.' : '登录已过期，请重新登录。')
      } else if (cause instanceof ApiError && cause.status === 422) {
        setField('next'); setError(copy.passwordRequirement)
      } else {
        setError(en ? 'Unable to confirm the change. Check your connection; the server may have saved it.' : '无法确认修改结果，请检查网络；服务端可能已保存，请勿反复提交。')
      }
    } finally { setBusy(false) }
  }
  return <section className="settings-card">
    <h2>{en ? 'Password' : '密码'}</h2>
    {saved && <p role="status">{en ? 'Password changed. Other sessions have been signed out.' : '密码已修改，其他设备已退出登录。'}</p>}
    {!open ? <button onClick={() => { clear(); setSaved(false); setOpen(true) }}>{en ? 'Change password' : '更改密码'}</button> : <form className="password-form" onSubmit={submit} aria-busy={busy}>
      <label>{en ? 'New password' : '新密码'}<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} pattern={'(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])(?=.*[^A-Za-z0-9\\s]).{8,128}'} disabled={busy} value={next} onChange={e => setNext(e.target.value)} aria-invalid={field === 'next'} aria-describedby="password-requirement" /></label>
      <small id="password-requirement">{copy.passwordRequirement}</small>
      <label>{en ? 'Confirm new password' : '确认新密码'}<input type="password" autoComplete="new-password" required maxLength={128} disabled={busy} value={confirmation} onChange={e => setConfirmation(e.target.value)} aria-invalid={field === 'confirmation'} aria-describedby={field === 'confirmation' ? 'password-change-error' : undefined} /></label>
      <p>{en ? 'Changing your password signs out other devices. This session stays signed in.' : '修改后其他设备将退出登录，当前登录保留。'}</p>
      {error && <p className="error" id="password-change-error" role="alert">{error}</p>}
      <div className="settings-row"><button className="primary" disabled={busy}>{busy ? (en ? 'Saving…' : '保存中…') : (en ? 'Confirm change' : '确认修改')}</button><button type="button" disabled={busy} onClick={() => { clear(); setOpen(false) }}>{en ? 'Cancel' : '取消'}</button></div>
    </form>}
  </section>
}
