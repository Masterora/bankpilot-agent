/**
 * 文件职责：显示导入产生的真实资金账户。
 * 主要内容：账户加载、失败重试与名称币种展示。
 * 关键边界：不展示银行卡状态、余额或推断尾号。
 */
import { useEffect, useState } from 'react'
import { api } from '../../api'

export function Accounts({ english }: { english: boolean }) {
  const [items, setItems] = useState<{ id: string; name: string; currency: string }[]>([])
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
          : <div className="account-list">{items.map((item) => <article className="account-tile" key={item.id}><strong>{item.name}</strong><p>{item.currency}</p></article>)}</div>}
  </section>
}
