/** 全局助手：会话仅保存在当前工作区内存，确认操作使用服务端提案 ID。 */
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import { apiErrorMessage } from '../../shared/apiErrors'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { DetailPanel } from '../../shared/DetailPanel'
import { LoadingIndicator } from '../../shared/ui'
import type { AssistantAction, ChatMessage, Reply } from './types'
import { AssistantEvidence } from './AssistantEvidence'
interface Turn {
  question: string
  reply: Reply
}
export function AssistantPanel({
  open,
  onClose,
  month,
  copy,
  locale,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  month: string
  copy: Messages
  locale: Locale
  onSaved: () => void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const lock = useRef(false)
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const pending = turns.some((turn) => turn.reply.action?.status === 'pending')
  const money = (amount: string, currency: string) => formatMoney(amount, currency, locale)
  const describe = (action: AssistantAction) => {
    const p = action.payload
    return `${p.month.slice(0, 7)} · ${copy.categoryLabels[p.category]} · ${p.currency}: ${action.before_amount ?? t('未设置', 'Not set')} → ${p.amount}`
  }
  function failure(cause: unknown) {
    return apiErrorMessage(cause, english, {
      planning_stale: [
        '预算已被修改，请取消此提案并重新提出修改。',
        'Budget changed. Cancel this proposal and request a new one.',
      ],
      assistant_action_expired: [
        '提案已过期，请取消后重新提出修改。',
        'Proposal expired. Cancel it and request a new one.',
      ],
      assistant_timeout: [
        '本次处理超时，输入已保留，请重试。',
        'Request timed out. Your input is retained; retry.',
      ],
      assistant_step_limit: [
        '本次查询步骤过多，请缩小问题范围。',
        'This question requires too many steps. Narrow its scope.',
      ],
      assistant_result_too_large: [
        '查询结果超过处理上限，请缩小问题范围。',
        'The result exceeds the processing limit. Narrow the question.',
      ],
      planning_period_limit: [
        '所选月份的数据超过处理上限，请选择其他月份。',
        'The selected month exceeds the processing limit. Choose another month.',
      ],
      narrow_period: [
        '所选月份的数据超过处理上限，请选择其他月份。',
        'The selected month exceeds the processing limit. Choose another month.',
      ],
      MODEL_OUTPUT_INVALID: [
        '助手未返回有效结果，请重试。',
        'The assistant returned an invalid result. Please retry.',
      ],
      MODEL_UNAVAILABLE: [
        '助手暂不可用，输入已保留，请稍后重试。',
        'The assistant is unavailable. Your input is retained; retry later.',
      ],
    })
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (lock.current || pending || !message.trim() || turns.length >= 7) return
    lock.current = true
    setBusy(true)
    setError('')
    const question = message.trim()
    const messages: ChatMessage[] = turns.flatMap((turn) => [
      { role: 'user', content: turn.question },
      {
        role: 'assistant',
        content:
          turn.reply.text +
          (turn.reply.action
            ? `\n${describe(turn.reply.action)}; status=${turn.reply.action.status}`
            : ''),
      },
    ])
    try {
      const reply = await api.assistantChat(
        [...messages, { role: 'user', content: question }],
        month,
        locale,
      )
      setTurns((current) => [...current, { question, reply }])
      setMessage('')
    } catch (cause) {
      setError(failure(cause))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  async function resolve(id: string, cancel: boolean) {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const action = await api.assistantAction(id, cancel)
      setTurns((current) =>
        current.map((turn) =>
          turn.reply.action?.id === id ? { ...turn, reply: { ...turn.reply, action } } : turn,
        ),
      )
      if (action.status === 'applied') onSaved()
    } catch (cause) {
      setError(failure(cause))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return (
    <DetailPanel
      open={open}
      title={t('账本助手', 'Ledger assistant')}
      closeLabel={t('收起', 'Close')}
      onClose={onClose}
    >
      <div className="assistant-conversation">
        {!turns.length && (
          <div className="assistant-intro">
            <h3>{t('想了解本月开销？', 'What would you like to know?')}</h3>
            <p>
              {t(
                '查询月度收支、预算与固定支出，也可以帮你调整预算。',
                'Ask about monthly spending, budgets and recurring costs, or change a budget.',
              )}
            </p>
            <div className="suggestions">
              {[
                t('本月哪些分类超预算了？', 'Which categories are over budget this month?'),
                t('本月和上月的支出有什么变化？', 'How did spending change from last month?'),
              ].map((text) => (
                <button
                  key={text}
                  disabled={busy}
                  onClick={() => {
                    setMessage(text)
                    input.current?.focus()
                  }}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((turn, index) => (
          <article className="assistant-turn" key={index}>
            <p className="assistant-question">{turn.question}</p>
            <p className="assistant-answer">{turn.reply.text}</p>
            <AssistantEvidence evidence={turn.reply.evidence} copy={copy} locale={locale} />
            {turn.reply.action && (
              <section className="assistant-proposal" aria-label={t('预算修改', 'Budget change')}>
                <strong>{describe(turn.reply.action)}</strong>
                {turn.reply.action.status === 'pending' ? (
                  <>
                    <p>
                      {t(
                        '确认后生效 · 15 分钟内有效',
                        'Applies after confirmation · Valid for 15 minutes',
                      )}
                    </p>
                    <div className="planning-actions">
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => void resolve(turn.reply.action!.id, false)}
                      >
                        {t('确认修改', 'Confirm change')}
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => void resolve(turn.reply.action!.id, true)}
                      >
                        {t('取消', 'Cancel')}
                      </button>
                    </div>
                  </>
                ) : (
                  <p role="status">
                    {turn.reply.action.status === 'cancelled'
                      ? t('已取消', 'Cancelled')
                      : t('已修改', 'Saved')}
                    {turn.reply.action.result &&
                      ` · ${t('执行后剩余', 'Remaining after change')} ${money(turn.reply.action.result.remaining, turn.reply.action.result.currency)}`}
                  </p>
                )}
              </section>
            )}
          </article>
        ))}
        {busy && <LoadingIndicator label={t('正在处理', 'Working')} />}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <form onSubmit={(event) => void submit(event)} className="assistant-composer">
          <label>
            {t('参考月份', 'Context month')} · {month.slice(0, 7)}
          </label>
          <textarea
            ref={input}
            onKeyDown={(event) => {
              if (
                (event.metaKey || event.ctrlKey) &&
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            aria-describedby="assistant-shortcut"
            aria-label={t('向助手提问', 'Ask the assistant')}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={1000}
            rows={3}
            disabled={busy || pending || turns.length >= 7}
            placeholder={
              pending
                ? t('先确认或取消上面的修改', 'Confirm or cancel the proposal first')
                : t('提问，或告诉我你想调整什么', 'Ask a question or request a change')
            }
          />
          <div className="planning-actions">
            <span id="assistant-shortcut" className="assistant-shortcut">
              ⌘ / Ctrl + Enter
            </span>
            <button
              className="primary"
              disabled={busy || pending || !message.trim() || turns.length >= 7}
            >
              {t('发送', 'Send')}
            </button>
            {turns.length > 0 && (
              <button
                type="button"
                disabled={busy || pending}
                onClick={() => {
                  setTurns([])
                  setError('')
                }}
              >
                {t('新对话', 'New conversation')}
              </button>
            )}
          </div>
          {turns.length >= 7 && (
            <p>{t('本段对话已达上限，请开始新对话。', 'Start a new conversation to continue.')}</p>
          )}
        </form>
      </div>
    </DetailPanel>
  )
}
