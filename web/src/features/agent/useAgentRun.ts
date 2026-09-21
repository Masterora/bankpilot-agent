/**
 * 文件职责：管理 Agent 运行的前端状态。
 *
 * 主要内容：处理查询提交、SSE 续读、终态获取和分类修正并发隔离。
 *
 * 关键边界：旧运行和旧修正响应不得覆盖当前运行，卸载时必须关闭事件流。
 */

import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../../api'
import { isPresetQuery } from '../../i18n'
import type { Messages } from '../../i18n'
import type { Run, TransactionCategory } from '../../types'

const terminalStatuses = new Set(['SUCCEEDED', 'FAILED', 'UNKNOWN'])

export function useAgentRun(copy: Messages) {
  const [message, setMessage] = useState(copy.defaultQuery)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [correctionSaved, setCorrectionSaved] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [correctingId, setCorrectingId] = useState<string | null>(null)
  const eventSource = useRef<EventSource | null>(null)
  const finishingRunId = useRef<string | null>(null)
  const activeRunId = useRef<string | null>(null)
  const correctionSequence = useRef(0)

  useEffect(() => {
    setMessage((current) => (isPresetQuery(current) ? copy.defaultQuery : current))
  }, [copy])

  useEffect(() => () => {
    activeRunId.current = null
    eventSource.current?.close()
  }, [])

  async function finishRun(runId: string) {
    if (activeRunId.current !== runId || finishingRunId.current === runId) return
    finishingRunId.current = runId
    eventSource.current?.close()
    eventSource.current = null
    try {
      const completed = await api.getRun(runId)
      if (activeRunId.current === runId) setRun(completed)
    } catch {
      if (activeRunId.current === runId) setError(copy.queryStatusFailed)
    } finally {
      if (finishingRunId.current === runId) finishingRunId.current = null
      if (activeRunId.current === runId) setSubmitting(false)
    }
  }

  function watchRun(runId: string) {
    eventSource.current?.close()
    eventSource.current = api.watchRunEvents(
      runId,
      (event) => {
        if (activeRunId.current !== runId) return
        setRun((current) => {
          if (current?.id !== runId || current.events.some((item) => item.sequence === event.sequence)) {
            return current
          }
          return { ...current, events: [...current.events, event].sort((a, b) => a.sequence - b.sequence) }
        })
        if (event.event_type === 'run.completed' || event.event_type === 'run.failed') {
          void finishRun(runId)
        }
      },
      () => {
        if (activeRunId.current !== runId || finishingRunId.current === runId) return
        void api.getRun(runId).then((current) => {
          if (activeRunId.current !== runId) return
          setRun(current)
          if (terminalStatuses.has(current.status)) {
            eventSource.current?.close()
            eventSource.current = null
            setSubmitting(false)
          }
        }).catch(() => {
          if (activeRunId.current !== runId) return
          eventSource.current?.close()
          setError(copy.queryStatusFailed)
          setSubmitting(false)
        })
      },
    )
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !message.trim()) return
    activeRunId.current = null
    correctionSequence.current += 1
    eventSource.current?.close()
    eventSource.current = null
    setCorrectingId(null)
    setError('')
    setRun(null)
    setCorrectionSaved(false)
    setSubmitting(true)
    try {
      const created = await api.createRun(message.trim())
      activeRunId.current = created.id
      setRun(created)
      if (terminalStatuses.has(created.status)) setSubmitting(false)
      else watchRun(created.id)
    } catch {
      setError(copy.createRunFailed)
      setSubmitting(false)
    }
  }

  async function correctCategory(transactionId: string, category: TransactionCategory) {
    if (!run) return
    const runId = run.id
    const sequence = ++correctionSequence.current
    const ownsResponse = () => activeRunId.current === runId
      && correctionSequence.current === sequence
    setError('')
    setCorrectingId(transactionId)
    try {
      const revision = run.result?.transactions.ledger_revision
      if (revision == null) throw new Error('Reload current evidence before editing')
      const updated = await api.correctCategory(runId, transactionId, category, revision)
      if (!ownsResponse()) return
      setRun((current) => current?.id === runId ? updated : current)
      setCorrectionSaved(true)
    } catch {
      if (ownsResponse()) setError(copy.categoryUpdateFailed)
    } finally {
      if (ownsResponse()) setCorrectingId(null)
    }
  }

  return {
    correctionSaved,
    correctingId,
    correctCategory,
    error,
    message,
    run,
    setMessage,
    submit,
    submitting,
  }
}
