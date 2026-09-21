/** 全局助手：会话保存在服务端，确认操作使用服务端提案 ID。 */
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import { apiErrorMessage } from '../../shared/apiErrors'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { DetailPanel } from '../../shared/DetailPanel'
import { LoadingIndicator } from '../../shared/ui'
import type { AssistantAction } from './types'
import { AssistantEvidence } from './AssistantEvidence'
import { SpendingDetails } from './SpendingDetails'
import { useConversations } from './useConversations'
import type { EvidenceTarget, SpendingScope, SpendingSummary } from './types'
export function AssistantPanel({
  userId,
  open,
  onClose,
  month,
  copy,
  locale,
  onSaved,
  ledgerRevision,
  onInspect,
}: {
  userId: string
  open: boolean
  onClose: () => void
  month: string
  copy: Messages
  locale: Locale
  onSaved: () => void
  ledgerRevision: number
  onInspect: (target: EvidenceTarget) => void
}) {
  const history = useConversations(userId, open, month)
  const turns = history.turns
  const context = history.scope
  const setContext = (scope: SpendingScope | null) => { void history.selectScope(scope).catch(cause => history.setError(cause)) }
  const [historyVisible, setHistoryVisible] = useState(false)
  const [message, setMessage] = useState('')
  const [sending, setBusy] = useState(false)
  const busy = sending || history.loading
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<{ summary: SpendingSummary; revision: number } | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const conversation = useRef<HTMLDivElement>(null)
  const readingPosition = useRef(0)
  function showDetail(summary: SpendingSummary, revision: number) {
    readingPosition.current = conversation.current?.parentElement?.scrollTop ?? 0
    setContext(summary.scope)
    setDetail({ summary, revision })
    setDetailVisible(true)
    conversation.current?.parentElement?.scrollTo({ top: 0 })
  }
  function backToAnswer() {
    setDetailVisible(false)
    requestAnimationFrame(() => conversation.current?.parentElement?.scrollTo({ top: readingPosition.current }))
  }
  const input = useRef<HTMLTextAreaElement>(null)
  const lock = useRef(false)
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const loadedRevision = useRef(ledgerRevision)
  const pending = history.processing || !!history.unknown
  const money = (amount: string, currency: string) => formatMoney(amount, currency, locale)
  const describe = (action: AssistantAction) => {
    const p = action.payload
    return `${p.month.slice(0, 7)} · ${copy.categoryLabels[p.category]} · ${p.currency}: ${action.before_amount ?? t('未设置', 'Not set')} → ${p.amount}`
  }
  function failure(cause: unknown) {
    return apiErrorMessage(cause, english, {
      assistant_conversation_limit: ['历史对话已达上限，请先删除不再需要的对话。', 'History limit reached. Delete a conversation to continue.'],
      assistant_turn_limit: ['本段对话已达上限，请新建对话继续。', 'Conversation limit reached. Start a new conversation.'],
      assistant_conversation_busy: ['正在处理，请稍后查看。', 'Processing. Check back shortly.'],
      assistant_conversation_deleted: ['这段对话已删除，请新建对话。', 'This conversation was deleted. Start a new one.'],
      assistant_request_not_found: ['尚未确认接收，可稍后查询或重试原问题。', 'Receipt unconfirmed. Check again or retry the original question.'],
      planning_stale: [
        '预算已被修改，请取消此提案并重新提出修改。',
        'Budget changed. Cancel this proposal and request a new one.',
      ],
      assistant_action_expired: [
        '提案已过期，请取消后重新提出修改。',
        'Proposal expired. Cancel it and request a new one.',
      ],
      assistant_timeout: [
        '处理超时，请重试。',
        'Request timed out. Retry.',
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
        '助手暂不可用，请稍后重试。',
        'Assistant unavailable. Retry later.',
      ],
    })
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (lock.current || pending || !message.trim()) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const accepted = await history.send({ protocol_version: 2, request_id: crypto.randomUUID(),
        ...(history.id ? { conversation_id: history.id } : { creation_id: crypto.randomUUID() }),
        question: message.trim(), month: history.month, locale, spending_context: context })
      if (accepted) setMessage('')
    } catch (cause) { setError(failure(cause)) }
    finally { lock.current = false; setBusy(false) }
  }
  async function resolve(id: string, cancel: boolean) {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const action = await api.assistantAction(id, cancel)
      history.setTurns((current) =>
        current.map((turn) =>
          turn.reply?.action?.id === id ? { ...turn, reply: { ...turn.reply!, action } } : turn,
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
      docked
      open={open}
      title={t('账本助手', 'Ledger assistant')}
      closeLabel={t('收起', 'Close')}
      onClose={onClose}
    >
      <div className="assistant-toolbar">
        <button disabled={busy || !!history.unknown} onClick={() => { history.fresh(); setHistoryVisible(false); setMessage(''); setDetail(null); setDetailVisible(false) }}><span aria-hidden="true">＋</span>{t('新对话', 'New conversation')}</button>
        <button aria-expanded={historyVisible} aria-controls="assistant-history" disabled={busy} onClick={() => setHistoryVisible(value => !value)}>{t('历史对话', 'History')}</button>
        {history.id && <button disabled={busy} onClick={() => {
          if (window.confirm(t('删除对话及待确认提案？已执行的预算修改不会撤销，历史备份可能仍保留对话。', 'Delete this conversation and pending proposals? Applied budgets are kept; old backups may retain history.'))) void history.remove().catch(cause => history.setError(cause))
        }}>{t('删除对话', 'Delete conversation')}</button>}
      </div>
      {historyVisible && <nav id="assistant-history" className="assistant-history" aria-label={t('历史对话', 'Conversation history')}>
        {history.items.map(item => <button key={item.id} aria-current={history.id === item.id ? "page" : undefined} disabled={busy || !!history.unknown} onClick={() => {
          setDetail(null); setDetailVisible(false); setMessage(''); void history.load(item.id).catch(cause => history.setError(cause))
        }}><strong>{item.title}</strong><time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleString(locale)}</time></button>)}
        {history.cursor && <button onClick={() => void history.list(history.cursor!).catch(cause => history.setError(cause))}>{t('更多', 'More')}</button>}
      </nav>}
      {history.storageFailed && <p role="alert">{t('浏览器存储不可用，刷新可能丢失待处理请求。', 'Browser storage unavailable: unacknowledged requests may not survive refresh.')}</p>}
      {history.unknown && <section role="status">
        <p>{t('接收状态未知，请先查询结果。', 'Receipt unknown. Check the result first.')}</p>
        <button disabled={busy} onClick={() => void history.lookup()}>{t('重新查询状态', 'Check status')}</button>
        <button disabled={busy} onClick={() => { setBusy(true); void history.send(history.unknown!).finally(() => setBusy(false)) }}>{t('重试本次发送', 'Retry original request')}</button>
      </section>}
      {history.before && <button disabled={busy} onClick={() => void history.load(history.id!, history.before!).catch(cause => history.setError(cause))}>{t('更早消息', 'Earlier messages')}</button>}
      {detail && <div hidden={!detailVisible}>
        <SpendingDetails key={`${detail.summary.calculated_at}:${JSON.stringify(detail.summary.scope)}`} summary={detail.summary} copy={copy} locale={locale}
          active={open && detailVisible} stale={detail.revision !== ledgerRevision} onBack={backToAnswer} onInspect={onInspect}
          onRequery={() => {
            setContext(detail.summary.scope)
            const scope = detail.summary.scope
            setMessage(`${scope.month.slice(0, 7)} ${copy.categoryLabels[scope.category]} ${scope.currency} ${t('实际支出和构成', 'spending and breakdown')}`)
            backToAnswer()
            requestAnimationFrame(() => input.current?.focus())
          }} />
      </div>}
      <div className="assistant-conversation" ref={conversation} hidden={detailVisible}>
        {!turns.length && (
          <div className="assistant-intro">
            <div className="suggestions">
              {[
                t('本月哪些分类超预算了？', 'Which categories are over budget this month?'),
                t('本月餐饮实际花了多少？', 'How much did I spend on dining this month?'),
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
        {turns.map((turn) => (
          <article className="assistant-turn" key={turn.id}>
            <p className="assistant-question">{turn.question}</p>
            <details className="assistant-message-meta"><summary>{t('详情', 'Details')}</summary><time dateTime={turn.created_at}>{new Date(turn.created_at).toLocaleString(locale)}</time><span>{turn.month.slice(0, 7)}{turn.scope && ` · ${copy.categoryLabels[turn.scope.category]} · ${turn.scope.currency}`}</span></details>
            {turn.status === 'processing' && <p role="status">{t('处理中…', 'Working…')}</p>}
            {turn.status === 'failed' && <p>{t('处理失败', 'Failed')} · {turn.error_code} <button disabled={busy || pending} onClick={() => {
              setBusy(true); void history.send({ protocol_version: 2, conversation_id: turn.conversation_id, request_id: crypto.randomUUID(), retry_of: turn.id,
                question: turn.question, month: turn.month, spending_context: turn.scope, locale }).finally(() => setBusy(false))
            }}>{t('重新处理', 'Retry')}</button></p>}
            {turn.reply && <>
            <p className="assistant-answer">{turn.reply.text}</p>
            {turn.reply.history_unavailable && <p>{t("历史详情不可用，请重新查询。", "History details unavailable. Query again.")}</p>}
            <button disabled={busy || pending} onClick={() => { setContext(turn.scope); setMessage(`${turn.month.slice(0, 7)} ${turn.scope ? copy.categoryLabels[turn.scope.category] + ' ' + turn.scope.currency : ''} ${t('重新查询当前账本', 'Query current ledger')}`) }}>{t('重新查询', 'Query again')}</button>
            <AssistantEvidence evidence={turn.reply.evidence} copy={copy} locale={locale} stale={loadedRevision.current !== ledgerRevision} onInspect={summary => showDetail(summary, ledgerRevision)} />
            {turn.reply.action && (
              <section className="assistant-proposal" aria-label={t('预算修改', 'Budget change')}>
                <strong>{describe(turn.reply.action)}</strong>
                {turn.reply.action.can_confirm ? (
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
                        onClick={() => void resolve(turn.reply!.action!.id, false)}
                      >
                        {t('确认修改', 'Confirm change')}
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => void resolve(turn.reply!.action!.id, true)}
                      >
                        {t('取消', 'Cancel')}
                      </button>
                    </div>
                  </>
                ) : (
                  <p role="status">
                    {turn.reply.action.effective_status === 'applied' ? t('当时已执行', 'Applied then') : ({ cancelled: t("已取消", "Cancelled"), expired: t("已过期", "Expired"), conflict: t("预算已变化，请重新提出修改", "Budget changed; request a new proposal"), unavailable: t("会话不可用", "Conversation unavailable"), pending: t("等待核对", "Awaiting review") }[turn.reply.action.effective_status])}
                    {turn.reply.action.result &&
                      ` · ${t('执行后剩余', 'Remaining after change')} ${money(turn.reply.action.result.remaining, turn.reply.action.result.currency)}`}
                  </p>
                )}
              </section>
            )}
            </>}
          </article>
        ))}
        {busy && <LoadingIndicator label={t('正在处理', 'Working')} />}
        {Boolean(error || history.error) && (
          <p className="error" role="alert">
            {error || failure(history.error)}
          </p>
        )}
        <form onSubmit={(event) => void submit(event)} className="assistant-composer">
          <label>
            {t('月份', 'Month')} · {history.month.slice(0, 7)}
          </label>
          {context && <p className="assistant-context">{t('追问范围', 'Follow-up scope')}：{context.month.slice(0, 7)} · {copy.categoryLabels[context.category]} · {context.currency} <button type="button" disabled={busy || pending} onClick={() => setContext(null)}>{t('清除', 'Clear')}</button></p>}
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
            disabled={busy || pending || (turns.at(-1)?.sequence ?? 0) >= history.limit}
            placeholder={
              pending
                ? t('先核对正在处理的请求', 'Check the pending request first')
                : t('输入问题', 'Enter a question')
            }
          />
          <div className="planning-actions">
            <span id="assistant-shortcut" className="assistant-shortcut">
              ⌘ / Ctrl + Enter
            </span>
            <button
              className="primary"
              disabled={busy || pending || !message.trim() || (turns.at(-1)?.sequence ?? 0) >= history.limit}
            >
              {t('发送', 'Send')}
            </button>
            {(turns.at(-1)?.sequence ?? 0) >= history.limit && (
              <button
                type="button"
                disabled={busy || pending}
                onClick={() => {
                  history.fresh(true)
                  setError('')
                  setDetail(null)
                  setDetailVisible(false)
                }}
              >
                {t('新对话继续所选范围', 'Continue scope in new conversation')}
              </button>
            )}
          </div>
          {(turns.at(-1)?.sequence ?? 0) >= history.limit && (
            <p>{t('本段对话已达上限，请开始新对话。', 'Start a new conversation to continue.')}</p>
          )}
        </form>
      </div>
    </DetailPanel>
  )
}
