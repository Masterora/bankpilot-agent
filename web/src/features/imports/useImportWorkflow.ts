/**
 * 文件职责：管理账单导入工作流状态。
 *
 * 主要内容：处理文件解码识别、账户匹配、字段映射、预览与确认导入。
 *
 * 关键边界：后一次文件选择使旧异步响应失效，金额解析和去重以服务端结果为准。
 */

import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

import { ApiError, api } from '../../api'
import type { Messages } from '../../i18n'
import type { Account, ImportBatch, ImportFieldMapping, ImportStatementPayload } from '../../types'
import { detectionError } from './detectionError'

const MAX_FILE_BYTES = 10 * 1024 * 1024

export interface ImportPreview {
  key: string
  skipped_rows: number
  excluded: { row_number: number; message: string }[]
  total_rows: number
  error_rows: number
  duplicate_rows: number
  errors: { row_number: number; message: string }[]
  rows: {
    row_number: number
    date: string
    occurred_at: string
    time_precision: 'unknown' | 'date' | 'timestamp'
    merchant: string
    amount: string
  }[]
}

interface WorkflowOptions {
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

export function useImportWorkflow({ active, copy, english, imports, onImported }: WorkflowOptions) {
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
  const [error, setError] = useState('')
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
        if (selected) setAccountName(selected.name)
      })
      .catch(() => {
        if (current) setAccountsFailed(true)
      })
    return () => {
      current = false
    }
  }, [imports, active, accountId, accountsAttempt])

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    await detectFile(file)
  }

  async function detectFile(file: File) {
    const selection = ++selectionSequence.current
    setRetryFile(null)
    setDetecting(false)
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
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setError(english ? 'Use CSV or XLSX. Decrypt archives on your device.' : '支持 CSV、XLSX；压缩包请在本机解密解压。')
      return
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(copy.imports.fileTooLarge)
      return
    }
    let text: string
    try {
      const bytes = new Uint8Array(await file.arrayBuffer())
      let binary = ''
      for (let offset = 0; offset < bytes.length; offset += 8192) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
      }
      text = (await api.decodeImport(file.name, btoa(binary))).content
    } catch (reason) {
      if (selection !== selectionSequence.current) return
      setError(
        reason instanceof ApiError && reason.status === 422
          ? reason.message
          : copy.imports.fileReadFailed,
      )
      if (!(reason instanceof ApiError) || reason.status >= 500) setRetryFile(file)
      return
    }
    if (selection !== selectionSequence.current) return
    if (!text.trim()) {
      setError(copy.imports.missingHeader)
      return
    }
    let detectedMapping: ImportFieldMapping
    setDetecting(true)
    try {
      const detection = await api.detectImport(text)
      const accountList = await api.listAccounts()
      if (selection !== selectionSequence.current) return
      setAccounts(accountList.items)
      setAccountsFailed(false)
      detectedMapping = detection.mapping
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
    } catch (reason) {
      if (selection !== selectionSequence.current) return
      const failure = detectionError(reason, english)
      setError(failure.message)
      if (failure.retry) setRetryFile(file)
      return
    } finally {
      if (selection === selectionSequence.current) setDetecting(false)
    }
    if (selection !== selectionSequence.current) return
    setFileName(file.name)
    setContent(text)
    setMapping(detectedMapping)
  }

  function updateMapping(field: keyof ImportFieldMapping, value: string) {
    setMapping((current) => ({ ...current, [field]: value || null }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit(accountName, content, currency, mapping)) return
    setError('')
    setSubmitting(true)
    try {
      if (!previewCurrent) {
        const report = await api.previewImport(payload)
        setPreview({ ...report, key: payloadKey })
        return
      }
      if (preview.error_rows) return
      const batch = await api.importStatement(payload)
      setResult(batch)
      setPreview(null)
      onImported(batch)
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 409
          ? copy.imports.conflict
          : copy.imports.importFailed,
      )
    } finally {
      setSubmitting(false)
    }
  }

  const selectedColumns = [mapping.occurred_at, mapping.merchant, mapping.amount].filter(Boolean)
  if (mapping.description) selectedColumns.push(mapping.description)
  const mappingHasDuplicates = headers.length > 0
    && selectedColumns.length !== new Set(selectedColumns).size
  const ready = canSubmit(accountName, content, currency, mapping) && !mappingHasDuplicates

  return {
    accountId, accountName, accounts, accountsFailed, content, currency, detecting, error,
    fileName, headers, mapping, mappingHasDuplicates, preview, previewCurrent, ready,
    result, retryFile, source, submitting, detectFile, selectFile, setAccountId,
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
