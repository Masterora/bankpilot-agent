/** User data export and explicitly confirmed deletion; credentials stay in memory. */
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../../api'
import { downloadFile } from '../../shared/download'

export function AccountData({ english, onDeleted }: { english: boolean; onDeleted: () => void }) {
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [operation, setOperation] = useState<'export' | 'delete'>('export')
  const lock = useRef(false)
  const t = (zh: string, en: string) => english ? en : zh
  function failure(cause: unknown) {
    if (cause instanceof ApiError) {
      if (cause.code === 'current_password_invalid') return t('当前密码不正确。', 'Current password is incorrect.')
      if (cause.code === 'account_work_pending') return t('仍有任务未结束，请先完成或核对任务后重试。', 'Tasks are still pending. Finish or reconcile them before retrying.')
      if (cause.code === 'account_export_capacity') return t('数据超过单次导出上限，请使用账本和月报的分批导出。', 'Data exceeds the export limit. Use ledger and report exports in smaller batches.')
      if (cause.status === 429) return t('操作过于频繁，请稍后重试。', 'Too many attempts. Try again later.')
      if (cause.status === 401) return t('登录已过期，请重新登录。', 'Session expired. Sign in again.')
    }
    return t('无法确认结果，请检查网络并核对账户状态。', 'Unable to confirm the result. Check your connection and account status.')
  }
  async function exportData() {
    if (lock.current) return
    lock.current = true; setOperation('export'); setBusy(true); setError(''); setSaved(false)
    try {
      const result = await api.accountExport()
      downloadFile(JSON.stringify(result, null, 2), 'bankpilot-account.json', 'application/json')
      setSaved(true)
    } catch (cause) { setError(failure(cause)) }
    finally { lock.current = false; setBusy(false) }
  }
  async function remove(event: FormEvent) {
    event.preventDefault()
    if (lock.current || confirmation !== 'DELETE') return
    lock.current = true; setOperation('delete'); setBusy(true); setError(''); setSaved(false)
    try { await api.deleteAccount(password, confirmation); setPassword(''); onDeleted() }
    catch (cause) { setPassword(''); setError(failure(cause)) }
    finally { lock.current = false; setBusy(false) }
  }
  return <><section className="settings-card">
    <h2>{t('账户数据', 'Account data')}</h2>
    <p>{t('导出账户、账本、规划、报告和对话数据，不包含密码或登录令牌。', 'Export your accounts, ledger, plans, reports and conversations, excluding passwords and session tokens.')}</p>
    <button disabled={busy} onClick={() => void exportData()}>{t('导出 JSON', 'Export JSON')}</button>
    {saved && <p role="status">{t('导出文件已生成。', 'Export file generated.')}</p>}
    {operation === 'export' && busy && <p role="status">{t('正在导出…', 'Exporting…')}</p>}
    {operation === 'export' && error && <p className="error" role="alert">{error}</p>}
  </section><section className="settings-card settings-danger">
    <h2>{t('注销账户', 'Delete account')}</h2>
    {!open ? <><p>{t('永久删除当前账户及个人数据，此操作不能撤销。', 'Permanently delete this account and its personal data. This cannot be undone.')}</p><button className="danger-button" disabled={busy} onClick={() => { setOpen(true); setOperation('delete'); setError('') }}>{t('注销账户…', 'Delete account…')}</button></> : <form className="password-form" onSubmit={remove} aria-busy={busy}>
      <p>{t('注销会永久删除当前服务中的账户及全部个人数据，并退出所有设备。已有离线备份仍可能保留数据；建议先导出。此操作不能撤销。', 'Deletion permanently removes this account and all personal data from this service and signs out every device. Existing offline backups may retain data. Export first; deletion cannot be undone.')}</p>
      <label>{t('当前密码', 'Current password')}<input type="password" autoComplete="current-password" required maxLength={128} disabled={busy} value={password} onChange={event => setPassword(event.target.value)} /></label>
      <label>{t('输入 DELETE 确认注销', 'Type DELETE to confirm deletion')}<input autoComplete="off" required pattern="DELETE" disabled={busy} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label>
      <div className="settings-row"><button className="danger-button" disabled={busy || confirmation !== 'DELETE'}>{t('永久注销账户', 'Permanently delete account')}</button><button type="button" disabled={busy} onClick={() => { setOpen(false); setPassword(''); setConfirmation(''); setError('') }}>{t('取消', 'Cancel')}</button></div>
    </form>}
    {operation === 'delete' && busy && <p role="status">{t('正在处理…', 'Processing…')}</p>}
    {operation === 'delete' && error && <p className="error" role="alert">{error}</p>}
  </section></>
}
