/**
 * 文件职责：管理账单导入工作流状态。
 *
 * 主要内容：处理文件解码识别、账户匹配、字段映射、预览与确认导入。
 *
 * 关键边界：后一次文件选择使旧异步响应失效，金额解析和去重以服务端结果为准。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

import { ApiError, api } from '../../api'
import type { Messages } from '../../i18n'
import type { Account, ImportBatch, ImportFieldMapping, ImportStatementPayload } from '../../types'
import { newIdempotencyKey } from '../../shared/operationKey'
import { clearPendingImport, readPendingImport, savePendingImport } from './importRecovery'
import type { PendingImport } from './importRecovery'
import { detectionError } from './detectionError'

const MAX_FILE_BYTES = 10 * 1024 * 1024

export type ImportPreview = import('../../types').ImportPreview & { key: string }

interface WorkflowOptions {
  userId: string
  active: boolean
  copy: Messages
  english: boolean
  imports: ImportBatch[]
  onImported: (batch: ImportBatch) => void
}

const emptyMapping: ImportFieldMapping = {
  occurred_at: '',
  merchant: '',
  amount: '',
  description: null,
}

export function useImportWorkflow({ userId, active, copy, english, imports, onImported }: WorkflowOptions) {
  const [initialRecovery] = useState(() => {
    try { return { pending: readPendingImport(userId), error: '' } }
    catch { return { pending: null, error: '无法读取恢复信息，请核对浏览器存储和导入历史。' } }
  })
  const [pending, setPending] = useState<PendingImport | null>(initialRecovery.pending)
  const pendingRef = useRef(pending)
  const busyRef = useRef(false)
  const importedRef = useRef(onImported)
  useEffect(() => { importedRef.current = onImported }, [onImported])
  const [contentDigest, setContentDigest] = useState('')
  const [fileName, setFileName] = useState('')
  const selectionSequence = useRef(0)
  const [content, setContent] = useState('')
  const [headers, setHeaders] = useState<string[]>([])
  const [accountName, setAccountName] = useState('')
  const [accountId, setAccountId] = useState('')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountsFailed, setAccountsFailed] = useState(false)
  const [accountsAttempt, setAccountsAttempt] = useState(0)
  const [currency, setCurrency] = useState('CNY')
  const [source, setSource] = useState('standard')
  const [mapping, setMapping] = useState<ImportFieldMapping>(emptyMapping)
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [error, setError] = useState(initialRecovery.error)
  const [submitting, setSubmitting] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [retryFile, setRetryFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const payload: ImportStatementPayload = {
    file_name: fileName,
    content,
    account_name: accountName.trim(),
    account_id: accountId || null,
    currency,
    mapping,
  }
  const payloadKey = JSON.stringify(payload)
  const previewCurrent = preview?.key === payloadKey

  useEffect(() => {
    if (!active) return
    let current = true
    api.listAccounts()
      .then((response) => {
        if (!current) return
        setAccounts(response.items)
        setAccountsFailed(false)
        const selected = response.items.find((account) => account.id === accountId)
        if (selected && !pendingRef.current) setAccountName(selected.name)
      })
      .catch(() => {
        if (current) setAccountsFailed(true)
      })
    return () => {
      current = false
    }
  }, [imports, active, accountId, accountsAttempt])

  // 先更新持久恢复信息，再同时更新 ref 与渲染状态；存储失败不能假装完成。
  const changePending = useCallback((value: PendingImport | null) => {
    if (value) savePendingImport(value)
    else clearPendingImport()
    pendingRef.current = value
    setPending(value)
  }, [])

  // 每条异步完成路径都绑定原 key，迟到的 A 响应不能清除 B 的恢复信息。
  const complete = useCallback((key: string, batch: ImportBatch) => {
    if (pendingRef.current?.key !== key) return
    changePending(null)
    setResult(batch)
    setPreview(null)
    setError('')
    setContent('')
    importedRef.current(batch)
  }, [changePending])

  useEffect(() => {
    const saved = pendingRef.current
    if (!active || !saved) return
    let current = true
    api.importByKey(saved.key).then((batch) => {
      if (!current) return
      complete(saved.key, batch)
    }).catch((reason) => {
      if (current && pendingRef.current?.key === saved.key) setError(reason instanceof ApiError && reason.status === 404
        ? '尚无已提交结果，请重新选择原文件恢复提交。'
        : '暂时无法查询原操作，请重试查询。')
    })
    return () => { current = false }
  }, [active, userId, complete])

  async function recover() {
    const saved = pendingRef.current
    if (!saved || busyRef.current) return
    busyRef.current = true
    setSubmitting(true)
    try {
      const batch = await api.importByKey(saved.key)
      complete(saved.key, batch)
    } catch (reason) {
      if (pendingRef.current?.key !== saved.key) return
      setError(reason instanceof ApiError && reason.status === 404
        ? '尚无已提交结果，请选择原文件后重试同一操作。' : '查询失败，原操作仍保留，请重试。')
    } finally {
      busyRef.current = false
      setSubmitting(false)
    }
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    await detectFile(file)
  }

  async function detectFile(file: File) {
    if (busyRef.current || initialRecovery.error) return
    if (file.size > MAX_FILE_BYTES || !/\.(csv|xlsx)$/i.test(file.name)) {
      setError(english ? 'Use a CSV or XLSX file up to 10 MB.' : '请选择不超过 10 MB 的 CSV 或 XLSX 文件。')
      return
    }
    const saved = pendingRef.current
    if (saved) {
      busyRef.current = true
      setDetecting(true)
      try {
        const decoded = await decodeFile(file)
        if (pendingRef.current?.key !== saved.key) return
        if (decoded.content_digest !== saved.content_digest) throw new Error('文件内容与原操作不同，请选择原文件。')
        setContent(decoded.content)
        setContentDigest(decoded.content_digest)
        setFileName(saved.config.file_name)
        setAccountId(saved.config.account_id ?? '')
        setAccountName(saved.config.account_name)
        setCurrency(saved.config.currency)
        setMapping(saved.config.mapping)
        setError('')
      } catch (reason) {
        if (pendingRef.current?.key === saved.key) setError(reason instanceof Error ? reason.message : '读取原文件失败')
      } finally {
        setDetecting(false)
        busyRef.current = false
      }
      return
    }
    const selection = ++selectionSequence.current
    setRetryFile(null)
    setPreview(null)
    setError('')
    setResult(null)
    setFileName('')
    setContent('')
    setHeaders([])
    setSource('standard')
    setAccountName('')
    setAccountId('')
    setCurrency('')
    setMapping(emptyMapping)
    let stage: 'decode' | 'detect' = 'decode'
    setDetecting(true)
    try {
      const decoded = await decodeFile(file)
      if (selection !== selectionSequence.current) return
      if (!decoded.content.trim()) {
        setError(copy.imports.missingHeader)
        return
      }
      stage = 'detect'
      const detection = await api.detectImport(decoded.content)
      const accountList = await api.listAccounts()
      if (selection !== selectionSequence.current) return
      setAccounts(accountList.items)
      setAccountsFailed(false)
      setSource(detection.source)
      setHeaders(detection.headers)
      const detectedCurrency = detection.currency || 'CNY'
      const compatibleAccounts = accountList.items.filter(
        (account) => account.source === detection.source && account.currency === detectedCurrency,
      )
      const matchingAccount = compatibleAccounts.find(
        (account) => account.name === detection.account_name,
      )
      if (matchingAccount) {
        setAccountId(matchingAccount.id)
        setAccountName(matchingAccount.name)
      } else if (!detection.account_name && compatibleAccounts.length === 1) {
        setAccountId(compatibleAccounts[0].id)
        setAccountName(compatibleAccounts[0].name)
      } else {
        setAccountName(
          detection.account_name
            || (detection.source === 'wechat'
              ? '日常账户'
              : detection.source === 'alipay' ? '支付账户' : ''),
        )
      }
      setCurrency(detectedCurrency)
      setContentDigest(decoded.content_digest)
      setFileName(file.name)
      setContent(decoded.content)
      setMapping(detection.mapping)
    } catch (reason) {
      if (selection !== selectionSequence.current) return
      if (stage === 'decode') {
        setError(reason instanceof ApiError && reason.status < 500
          ? reason.message : copy.imports.fileReadFailed)
        if (!(reason instanceof ApiError) || reason.status >= 500) setRetryFile(file)
      } else {
        const failure = detectionError(reason, english)
        setError(failure.message)
        if (failure.retry) setRetryFile(file)
      }
    } finally {
      if (selection === selectionSequence.current) setDetecting(false)
    }
  }

  function updateMapping(field: keyof ImportFieldMapping, value: string) {
    setMapping((current) => ({ ...current, [field]: value || null }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (initialRecovery.error || busyRef.current || !canSubmit(accountName, content, currency, mapping)) return
    setError('')
    busyRef.current = true
    setSubmitting(true)
    const selection = selectionSequence.current
    const resuming = Boolean(pendingRef.current)
    let submittedKey: string | null = null
    try {
      let saved = pendingRef.current
      if (!saved && !previewCurrent) {
        const report = await api.previewImport(payload)
        if (selection === selectionSequence.current) setPreview({ ...report, key: payloadKey })
        return
      }
      if (!saved) {
        if (!preview || preview.error_rows) return
        const { content: _content, ...config } = payload
        void _content
        saved = {
          user_id: userId, key: newIdempotencyKey(), config,
          request_digest: preview.request_digest, content_digest: contentDigest,
        }
        changePending(saved)
      }
      submittedKey = saved.key
      const batch = await api.importStatement({ ...saved.config, content, idempotency_key: saved.key })
      complete(saved.key, batch)
    } catch (reason) {
      if (submittedKey !== null && pendingRef.current?.key !== submittedKey) return
      if (!resuming && reason instanceof ApiError && [401, 413, 422].includes(reason.status)) {
        changePending(null)
      }
      setError(reason instanceof Error ? reason.message : copy.imports.importFailed)
    } finally {
      busyRef.current = false
      setSubmitting(false)
    }
  }

  const selectedColumns = [mapping.occurred_at, mapping.merchant, mapping.amount].filter(Boolean)
  for (const field of [mapping.description, mapping.transaction_id, mapping.account, mapping.currency]) {
    if (field) selectedColumns.push(field)
  }
  const mappingHasDuplicates = headers.length > 0
    && selectedColumns.length !== new Set(selectedColumns).size
  const ready = canSubmit(accountName, content, currency, mapping) && !mappingHasDuplicates

  return {
    accountId, accountName, accounts, accountsFailed, content, currency, detecting, error,
    fileName, headers, mapping, mappingHasDuplicates, preview, previewCurrent, ready,
    result, retryFile, source, submitting, pending, recover, detectFile, selectFile, setAccountId,
    setAccountName, setAccountsAttempt, setCurrency, submit, updateMapping,
  }
}

function canSubmit(
  accountName: string,
  content: string,
  currency: string,
  mapping: ImportFieldMapping,
) {
  return Boolean(
    accountName.trim()
      && content
      && /^[A-Z]{3}$/.test(currency)
      && mapping.occurred_at
      && mapping.merchant
      && mapping.amount,
  )
}

async function decodeFile(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
  }
  return api.decodeImport(file.name, btoa(binary))
}
