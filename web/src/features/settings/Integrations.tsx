import { useCallback, useEffect, useRef, useState } from 'react'
import { newIdempotencyKey } from '../../shared/operationKey'
import { api, ApiError } from '../../api'
import type { IntegrationStatus, SandboxOrder } from '../../api'

const states: Record<string, [string, string]> = {
  WAIT_BUYER_PAY: ['待支付', 'Awaiting payment'],
  TRADE_SUCCESS: ['支付成功', 'Paid'],
  TRADE_FINISHED: ['交易完成', 'Completed'],
  TRADE_CLOSED: ['交易关闭', 'Closed'],
}

function message(error: unknown, english: boolean) {
  if (error instanceof ApiError) {
    const messages: Record<string, [string, string]> = {
      integration_rate_limited: [
        '操作过于频繁，请稍后再试。',
        'Too many requests. Try again later.',
      ],
      feishu_already_bound: ['账号已绑定，请刷新状态。', 'Already linked. Refresh the status.'],
      alipay_operation_conflict: [
        '重试参数已改变，请重新填写支付信息。',
        'Retry details changed. Re-enter the payment.',
      ],
      alipay_query_failed: [
        '暂时无法查询，请稍后重试。',
        'Could not check payment. Try again later.',
      ],
      alipay_checkout_failed: [
        '暂时无法创建支付链接，请稍后重试。',
        'Could not create checkout. Try again later.',
      ],
    }
    if (messages[error.code]) return messages[error.code][english ? 1 : 0]
  }
  return english
    ? 'Could not complete this request. Refresh and try again.'
    : '操作未完成，请刷新后重试。'
}

function checkoutUrl(value: string | null) {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.origin === 'https://openapi-sandbox.dl.alipaydev.com' &&
      url.pathname === '/gateway.do'
      ? value
      : null
  } catch {
    return null
  }
}

export function Integrations({ english: en }: { english: boolean }) {
  const [status, setStatus] = useState<IntegrationStatus | null>(null)
  const [orders, setOrders] = useState<SandboxOrder[]>([])
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [statusFailed, setStatusFailed] = useState(false)
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [ordersFailed, setOrdersFailed] = useState(false)
  const statusRequest = useRef(0)
  const ordersRequest = useRef(0)
  const codeGeneration = useRef(0)
  const [error, setError] = useState('')
  const [errorSection, setErrorSection] = useState('feishu')
  const lock = useRef(false)
  const [subject, setSubject] = useState('')
  const [amount, setAmount] = useState('1.00')
  const [confirmed, setConfirmed] = useState(false)
  const operation = useRef<string | null>(null)
  const lang = en ? 1 : 0

  const loadOrders = useCallback(async () => {
    const request = ++ordersRequest.current
    setOrdersLoading(true)
    setOrdersFailed(false)
    try {
      const list = await api.sandboxOrders()
      if (request === ordersRequest.current) setOrders(list)
    } catch {
      if (request === ordersRequest.current) setOrdersFailed(true)
    } finally {
      if (request === ordersRequest.current) setOrdersLoading(false)
    }
  }, [])

  const load = useCallback(async () => {
    const request = ++statusRequest.current
    setStatusFailed(false)
    try {
      const next = await api.integrations()
      if (request !== statusRequest.current) return
      setStatus(next)
      if (next.feishu_bound || !next.feishu_enabled) {
        codeGeneration.current++
        setCode(null)
      }
      if (next.alipay_sandbox_enabled) {
        void loadOrders()
      } else {
        ordersRequest.current++
        setOrders([])
        setOrdersLoading(false)
        setOrdersFailed(false)
      }
    } catch {
      if (request === statusRequest.current) setStatusFailed(true)
    } finally {
      if (request === statusRequest.current) setLoading(false)
    }
  }, [loadOrders])

  useEffect(() => {
    const status = statusRequest
    const orders = ordersRequest
    const codes = codeGeneration
    const refresh = () => {
      codeGeneration.current++
      setCode(null)
      void load()
    }
    void load()
    window.addEventListener('bankpilot:integrations-changed', refresh)
    return () => {
      status.current++
      orders.current++
      codes.current++
      window.removeEventListener('bankpilot:integrations-changed', refresh)
    }
  }, [load])

  function recordOrder(order: SandboxOrder) {
    // A list read started before this write cannot replace the new result.
    ordersRequest.current++
    setOrdersLoading(false)
    setOrders((previous) => {
      const updated = previous.map((item) => (item.id === order.id ? order : item))
      return previous.some((item) => item.id === order.id)
        ? updated
        : [order, ...updated].slice(0, 20)
    })
  }

  async function perform(action: () => Promise<void>, section = 'feishu') {
    if (lock.current) return
    lock.current = true
    setErrorSection(section)
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(message(err, en))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  if (loading)
    return (
      <section className="settings-card" aria-busy="true">
        <h2>{en ? 'Connections' : '外部接入'}</h2>
        <p role="status">{en ? 'Loading…' : '加载中…'}</p>
      </section>
    )
  return (
    <>
      <section className="settings-card integration-card">
        <h2>{en ? 'Feishu' : '飞书'}</h2>
        {status ? (
          <>
            <p>
              {status.feishu_bound
                ? en
                  ? `Linked ${status.feishu_identity}`
                  : `已绑定 ${status.feishu_identity}`
                : status.feishu_enabled
                  ? en
                    ? 'Not linked'
                    : '未绑定'
                  : en
                    ? 'Not enabled. An administrator must configure the application bot.'
                    : '尚未启用，请管理员配置飞书应用机器人。'}
            </p>
            <p>
              {en
                ? 'Private messages can query your ledger. Budget proposals require confirmation on the website.'
                : '私聊机器人查询账本，预算提案需回到网页确认。'}
            </p>
            {code && (
              <div className="integration-code" role="status">
                <p>{en ? 'Send this privately to the bot:' : '在机器人私聊中发送：'}</p>
                <code>绑定 {code.code}</code>
                <p>
                  {en ? 'Expires at ' : '有效期至 '}
                  {new Date(code.expires_at).toLocaleTimeString(en ? 'en-US' : 'zh-CN')}。
                  {en ? 'Keep this code private.' : '请勿转发绑定码。'}
                </p>
              </div>
            )}
            <div className="settings-row">
              {status.feishu_enabled && !status.feishu_bound && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void perform(async () => {
                      const generation = codeGeneration.current
                      const next = await api.feishuBindingCode()
                      if (generation === codeGeneration.current) setCode(next)
                    })
                  }
                >
                  {en ? 'Get binding code' : '获取绑定码'}
                </button>
              )}
              {status.feishu_bound && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void perform(async () => {
                      await api.feishuUnbind()
                      setCode(null)
                      await load()
                    })
                  }
                >
                  {en ? 'Unlink Feishu' : '解除绑定'}
                </button>
              )}
              <button disabled={busy} onClick={() => void load()}>
                {en ? 'Refresh status' : '刷新状态'}
              </button>
            </div>
          </>
        ) : (
          <button disabled={busy} onClick={() => void load()}>
            {en ? 'Retry' : '重新加载'}
          </button>
        )}
        {statusFailed && (
          <p className="error" role="alert">
            {en ? 'Could not load connection status.' : '无法读取接入状态。'}
          </p>
        )}
        {error && errorSection === 'feishu' && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
      <section className="settings-card integration-card">
        <h2>{en ? 'Alipay sandbox' : '支付宝沙箱'}</h2>
        <p>
          {en
            ? 'Test payments use sandbox funds and do not change your ledger.'
            : '仅使用沙箱测试资金，支付结果不计入个人账本。'}
        </p>
        {!status ? (
          <p>{en ? 'Connection status unavailable.' : '接入状态暂不可用。'}</p>
        ) : !status.alipay_sandbox_enabled ? (
          <p>
            {en
              ? 'Not enabled. An administrator must configure sandbox credentials.'
              : '尚未启用，请管理员配置沙箱应用和密钥。'}
          </p>
        ) : (
          <>
            <form
              className="integration-form"
              onSubmit={(event) => {
                event.preventDefault()
                if (!confirmed) return
                void perform(async () => {
                  operation.current ??= newIdempotencyKey()
                  const order = await api.sandboxCreate(operation.current, subject, amount)
                  recordOrder(order)
                  operation.current = null
                  setConfirmed(false)
                }, 'alipay')
              }}
            >
              <label>
                {en ? 'Payment subject' : '支付说明'}
                <input
                  value={subject}
                  required
                  maxLength={80}
                  disabled={busy}
                  onChange={(event) => {
                    setSubject(event.target.value)
                    operation.current = null
                    setConfirmed(false)
                  }}
                />
              </label>
              <label>
                {en ? 'Amount (CNY)' : '金额（人民币）'}
                <input
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  max="10000"
                  step="0.01"
                  value={amount}
                  required
                  disabled={busy}
                  onChange={(event) => {
                    setAmount(event.target.value)
                    operation.current = null
                    setConfirmed(false)
                  }}
                />
              </label>
              <label className="integration-confirm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={busy}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                {en
                  ? `I confirm a sandbox payment of CNY ${amount}`
                  : `确认创建 ¥${amount} 的沙箱支付`}
              </label>
              <button type="submit" disabled={busy || !confirmed || !subject.trim()}>
                {busy
                  ? en
                    ? 'Processing…'
                    : '处理中…'
                  : en
                    ? 'Create sandbox payment'
                    : '创建沙箱支付'}
              </button>
            </form>
            {ordersLoading && <p role="status">{en ? 'Loading orders…' : '正在读取订单…'}</p>}
            {ordersFailed && (
              <p className="error" role="alert">
                {en ? 'Could not load orders.' : '无法读取订单。'}{' '}
                <button disabled={busy} onClick={() => void loadOrders()}>
                  {en ? 'Retry orders' : '重试读取订单'}
                </button>
              </p>
            )}
            {!ordersLoading && !ordersFailed && orders.length === 0 && (
              <p>{en ? 'No sandbox payments yet.' : '暂无沙箱订单。'}</p>
            )}
            <ul className="integration-orders">
              {orders.map((order) => {
                const href = checkoutUrl(order.checkout_url)
                return (
                  <li key={order.id}>
                    <div>
                      <strong>{order.subject}</strong>
                      <span>
                        ¥{order.amount} · {states[order.status]?.[lang] ?? order.status}
                      </span>
                    </div>
                    <small>
                      {en ? 'Order ' : '订单 '}
                      {order.id}
                    </small>
                    <div className="settings-row">
                      {href && (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {en ? 'Open sandbox checkout' : '前往沙箱付款'}
                        </a>
                      )}
                      <button
                        disabled={busy}
                        onClick={() =>
                          void perform(async () => {
                            const next = await api.sandboxQuery(order.id)
                            recordOrder(next)
                          }, 'alipay')
                        }
                      >
                        {en ? 'Check payment' : '查询支付状态'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        )}
        {error && errorSection === 'alipay' && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
    </>
  )
}
