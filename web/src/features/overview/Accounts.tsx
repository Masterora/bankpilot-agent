/**
 * 文件职责：显示导入产生的真实资金账户。
 * 主要内容：账户加载、失败重试、来源展示及稳定 ID 下的名称修改。
 * 关键边界：不展示银行卡状态、余额或推断尾号。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Account } from '../../types'

export function Accounts({ english }: { english: boolean }) {
  const [items, setItems] = useState<Account[]>([])
  const [state, setState] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api.listAccounts().then((value) => { if (active) { setItems(value.items); setState('ready') } })
      .catch(() => { if (active) setState('failed') })
    return () => { active = false }
  }, [attempt])
  return <section className="accounts-section"><h2>{english ? 'Accounts' : '资金账户'}</h2>
    {state === 'loading' ? <p>{english ? 'Loading' : '正在读取'}</p>
      : state === 'failed' ? <button onClick={() => setAttempt(attempt + 1)}>{english ? 'Retry' : '重新读取账户'}</button>
        : items.length === 0 ? <p>{english ? 'Import a statement to create an account' : '导入账单后显示账户'}</p>
          : <div className="account-list">{items.map((item) => <AccountTile key={item.id} item={item} english={english} onSaved={() => setAttempt((a) => a + 1)} />)}</div>}
  </section>
}

/** 名称是可编辑标签；保存后 ID、来源和已有流水归属保持稳定。 */
function AccountTile({ item, english, onSaved }: { item: Account; english: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(item.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <article className="account-tile"><strong>{item.name}</strong><p>{item.currency} · {item.source === 'wechat' ? (english ? 'WeChat' : '微信') : item.source === 'alipay' ? (english ? 'Alipay' : '支付宝') : (english ? 'Statement' : '标准账单')}</p>
    {editing ? <form onSubmit={async (event) => {
      event.preventDefault(); setBusy(true); setError('')
      try { await api.renameAccount(item.id, name.trim()); setEditing(false); onSaved() }
      catch { setError(english ? 'Save failed. Check for an existing name.' : '保存失败，请检查名称是否重复。') }
      finally { setBusy(false) }
    }}><input aria-label={english ? 'Account name' : '账户名称'} value={name} maxLength={100} required disabled={busy} onChange={(e) => setName(e.target.value)} /><button disabled={busy || !name.trim()}>{english ? 'Save' : '保存'}</button><button type="button" disabled={busy} onClick={() => setEditing(false)}>{english ? 'Cancel' : '取消'}</button>{error && <p role="alert">{error}</p>}</form>
      : <button onClick={() => { setName(item.name); setEditing(true) }}>{english ? 'Rename' : '重命名'}</button>}
  </article>
}
