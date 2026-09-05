/**
 * 文件职责：提供 CSV 账单选择、字段映射、原子写入和批次报告界面。
 *
 * 主要内容：
 * - 调用服务端识别 CSV 字段与显式账户信息，允许查看字段对应。
 * - 收集账户与币种，将源文本交给受认证 API 做确定性校验和去重。
 * - 展示最近一次结果、失败行和当前用户的导入历史。
 *
 * 关键边界：浏览器不解析金额或决定去重结果；服务端是校验、写入与批次状态的唯一权威。
 */

import { ChangeEvent, FormEvent, useRef, useState } from 'react'

import { ApiError, api } from '../../api'
import type { Messages } from '../../i18n'
import type { ImportBatch, ImportFieldMapping } from '../../types'
import { detectionError } from './detectionError'
import { formatTimestamp, formatTransactionTime } from '../../format'

const MAX_FILE_BYTES = 10 * 1024 * 1024
export function ImportPage({
  copy,
  english,
  failed,
  imports,
  loading,
  onImported,
  onAnalyze,
  onRetryHistory,
}: {
  copy: Messages
  english: boolean
  failed: boolean
  imports: ImportBatch[]
  loading: boolean
  onImported: (batch: ImportBatch) => void
  onAnalyze: () => void
  onRetryHistory: () => void
}) {
  const [fileName, setFileName] = useState('')
  const selectionSequence = useRef(0)
  const [content, setContent] = useState('')
  const [headers, setHeaders] = useState<string[]>([])
  const [accountName, setAccountName] = useState('')
  const [currency, setCurrency] = useState('CNY')
  const [source, setSource] = useState('standard')
  const [mapping, setMapping] = useState<ImportFieldMapping>({
    occurred_at: '',
    merchant: '',
    amount: '',
    description: null,
  })
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [retryFile, setRetryFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<{ key: string; skipped_rows: number; excluded: { row_number: number; message: string }[]; total_rows: number; error_rows: number; duplicate_rows: number; errors: { row_number: number; message: string }[]; rows: { row_number: number; date: string; occurred_at: string; time_precision: 'unknown' | 'date' | 'timestamp'; merchant: string; amount: string }[] } | null>(null)
  const payload = { file_name: fileName, content, account_name: accountName.trim(), currency, mapping }
  const payloadKey = JSON.stringify(payload)
  const previewCurrent = preview?.key === payloadKey

  // 文件只在浏览器内读取为文本；清空选择器后仍可重新选择同一文件。
  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    await detectFile(file)
  }

  // 服务故障时只在组件内存保留文件供重试；后一次选择使前一次异步结果失效。
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
    setCurrency('')
    setMapping({ occurred_at: '', merchant: '', amount: '', description: null })
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
      setError(reason instanceof ApiError && reason.status === 422 ? reason.message : copy.imports.fileReadFailed)
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
      if (selection !== selectionSequence.current) return
      detectedMapping = detection.mapping
      setSource(detection.source)
      setHeaders(detection.headers)
      if (detection.account_name) setAccountName(detection.account_name)
      if (detection.currency) setCurrency(detection.currency)
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

  // 前端只提交映射意图，导入成败、金额解析和去重全部以服务端报告为准。
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
      const batch = await api.importStatement({
        file_name: fileName,
        content,
        account_name: accountName.trim(),
        currency,
        mapping,
      })
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

  return (
    <section className="product-page">
      <header className="page-header">
        <h1>{copy.productPages.import.title}</h1>
        <p>UTC+8</p>
      </header>
      <details className="import-report"><summary>{english ? 'Supported files' : '支持的文件与获取方式'}</summary><p>{english ? 'Alipay and WeChat personal bill layouts · CSV / XLSX. Unsupported layouts are rejected. Decrypt archives on your device; never provide a payment password.' : '支付宝、微信个人账单结构 · CSV / XLSX。未知格式拒绝导入；压缩包在本机解密解压，不要提供支付密码。'}</p></details>

      <form className="import-workspace" onSubmit={submit}>
        <section className="import-source-panel">
          <label className="file-drop">
            <input type="file" accept=".csv,.xlsx" onChange={selectFile} />
            <span className="file-drop-icon" aria-hidden="true">↑</span>
            <strong>{fileName || copy.imports.chooseFile}</strong>
            <span>{copy.imports.fileRequirements}</span>
          </label>
          <div className="import-account-grid">
            <label>
              {copy.imports.accountName}
              <input
                list="statement-accounts"
                maxLength={100}
                placeholder={copy.imports.accountPlaceholder}
                required
                value={accountName}
                onChange={(event) => setAccountName(event.target.value)}
              />
              <datalist id="statement-accounts">{[...new Set(imports.map((batch) => batch.account_name))].filter((name) => source === 'standard' || name.startsWith(source === 'alipay' ? '支付宝 · ' : '微信 · ')).map((name) => <option key={name} value={name} />)}</datalist>
            </label>
            <label>
              {copy.imports.currency}
              <input
                aria-label={copy.imports.currency}
                readOnly={source !== 'standard'}
                inputMode="text"
                maxLength={3}
                pattern="[A-Za-z]{3}"
                placeholder={copy.imports.currencyPlaceholder}
                required
                value={currency}
                onChange={(event) => setCurrency(event.target.value.replace(/[^A-Za-z]/g, '').toUpperCase())}
              />
            </label>
          </div>
        </section>

        <section className="import-mapping-panel">
          <div className="import-panel-heading">
            <div><p className="eyebrow">{copy.imports.mappingEyebrow}</p><h2>{copy.imports.mappingHeading}</h2></div>
            <span>{headers.length ? `${headers.length} ${copy.imports.columns}` : copy.imports.pending}</span>
          </div>
          {headers.length === 0 ? (
            <p className="import-placeholder">{copy.imports.mappingEmpty}</p>
          ) : source !== 'standard' ? <p>{source === 'alipay' ? '支付宝' : '微信'} · {english ? 'Source fields locked · UTC+8' : '来源字段已识别 · UTC+8'}</p> : (
            <details><summary>{english ? 'Field mapping' : '查看字段对应'}</summary><div className="mapping-fields">
              <MappingSelect
                copy={copy}
                field="occurredAt"
                headers={headers}
                required
                value={mapping.occurred_at}
                onChange={(value) => updateMapping('occurred_at', value)}
              />
              <MappingSelect
                copy={copy}
                field="merchant"
                headers={headers}
                required
                value={mapping.merchant}
                onChange={(value) => updateMapping('merchant', value)}
              />
              <MappingSelect
                copy={copy}
                field="amount"
                headers={headers}
                required
                value={mapping.amount}
                onChange={(value) => updateMapping('amount', value)}
              />
              <MappingSelect
                copy={copy}
                field="description"
                headers={headers}
                value={mapping.description ?? ''}
                onChange={(value) => updateMapping('description', value)}
              />
            </div></details>
          )}
          {mappingHasDuplicates && <p className="error">{copy.imports.duplicateMapping}</p>}
          <button className="primary import-submit" disabled={!ready || submitting || (previewCurrent && preview.error_rows > 0)}>
            {submitting && <span className="button-spinner" aria-hidden="true" />}
            {submitting ? copy.imports.importing : previewCurrent ? (english ? 'Confirm import' : '确认导入') : (english ? 'Preview statement' : '预览账单')}
          </button>
        </section>
      </form>
      {previewCurrent && <section className="import-report"><h2>{english ? 'Import preview' : '导入预览'}</h2><p>{preview.skipped_rows} {english ? 'excluded' : '行排除'} · {preview.total_rows} {english ? 'rows' : '行'} · {preview.duplicate_rows} {english ? 'duplicates' : '行重复'} · {preview.error_rows} {english ? 'invalid rows' : '行格式异常'}</p>{preview.error_rows > 0 && <p role="alert">{english ? 'This format cannot be imported. Check the field selection or use a supported source file.' : '该格式无法导入。请核对字段选择，或使用已适配的来源文件。'}</p>}<details><summary>{english ? 'Excluded rows' : '排除明细'}</summary>{preview.excluded.map((item) => <p key={item.row_number}>{item.row_number} · {item.message}</p>)}</details><ul>{preview.errors?.map((item) => <li key={item.row_number}>{english ? 'Row' : '第'} {item.row_number}: {item.message}</li>)}</ul><p>{english ? 'First 20 rows · UTC+8' : '前 20 行 · UTC+8'}</p><div className="import-table-wrap"><table className="import-table"><tbody>{preview.rows.map((row) => <tr key={row.row_number}><td>{formatTransactionTime({ booking_date: row.date, occurred_at: row.occurred_at, time_precision: row.time_precision }, english ? 'en-US' : 'zh-CN')}</td><td>{row.merchant}</td><td>{row.amount} {currency}</td></tr>)}</tbody></table></div></section>}

      {error && <p className="error import-page-error" role="alert">{error}</p>}
      {detecting && <p role="status">{english ? 'Recognizing statement' : '正在识别账单'}</p>}
      {retryFile && <button type="button" disabled={detecting} onClick={() => void detectFile(retryFile)}>{english ? 'Retry detection' : '重试识别'}</button>}
      {result && <>
        <ImportReport batch={result} copy={copy} english={english} />
        {result.status !== 'REJECTED' && <div className="import-next"><button type="button" className="primary" onClick={onAnalyze}>{copy.openAgent}<span aria-hidden="true"> →</span></button></div>}
      </>}
      {failed && <button type="button" onClick={onRetryHistory}>{english ? 'Retry history' : '重新读取历史'}</button>}
      <ImportHistory copy={copy} english={english} failed={failed} imports={imports} loading={loading} onRevoked={onImported} />
    </section>
  )
}

function MappingSelect({
  copy,
  field,
  headers,
  onChange,
  required = false,
  value,
}: {
  copy: Messages
  field: 'occurredAt' | 'merchant' | 'amount' | 'description'
  headers: string[]
  onChange: (value: string) => void
  required?: boolean
  value: string
}) {
  return (
    <label>
      <span>{copy.imports[field]}{required ? ' *' : ''}</span>
      <select required={required} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{required ? copy.imports.selectColumn : copy.imports.notMapped}</option>
        {headers.map((header) => <option key={header} value={header}>{header}</option>)}
      </select>
    </label>
  )
}

function ImportReport({ batch, copy, english }: { batch: ImportBatch; copy: Messages; english: boolean }) {
  return (
    <section className="import-report" aria-live="polite">
      <div className="import-panel-heading">
        <div><p className="eyebrow">{copy.imports.reportEyebrow}</p><h2>{copy.imports.reportHeading}</h2></div>
        <ImportStatus batch={batch} copy={copy} />
      </div>
      <div className="import-metrics">
        <Metric label={copy.imports.totalRows} value={batch.total_rows} />
        <Metric label={copy.imports.importedRows} value={batch.imported_rows} />
        <Metric label={copy.imports.duplicateRows} value={batch.duplicate_rows} />
        <Metric label={copy.imports.errorRows} value={batch.error_rows} />
        <Metric label={english ? 'Excluded' : '排除'} value={batch.skipped_rows} />
      </div>
      {batch.excluded?.length > 0 && <details><summary>{english ? 'Excluded rows' : '排除明细'}</summary>{batch.excluded.map((row) => <p key={row.row_number}>{row.row_number} · {row.message}</p>)}</details>}
      {batch.errors.length > 0 && (
        <ol className="import-errors">
          {batch.errors.map((item) => (
            <li key={`${item.row_number}-${item.code}`}>
              <strong>{copy.imports.row} {item.row_number}</strong>
              <span>{copy.imports.errorCodes[item.code] ?? item.message}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function ImportHistory({
  copy,
  english,
  failed,
  imports,
  loading,
  onRevoked,
}: {
  copy: Messages
  english: boolean
  failed: boolean
  imports: ImportBatch[]
  loading: boolean
  onRevoked: (batch: ImportBatch) => void
}) {
  const [pending, setPending] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  async function revoke(batch: ImportBatch) {
    setBusy(true); setError(false)
    try { await api.revokeImport(batch.id); onRevoked({ ...batch, status: 'REVOKED' }); setPending(null) }
    catch { setError(true) }
    finally { setBusy(false) }
  }
  return (
    <section className="import-history">
      <div className="import-panel-heading">
        <div><p className="eyebrow">{copy.imports.historyEyebrow}</p><h2>{copy.imports.historyHeading}</h2></div>
      </div>
      {error && <p role="alert">{english ? 'Revocation failed. Retry.' : '撤销失败，请重试。'}</p>}
      {loading ? <p className="import-placeholder">{copy.imports.loading}</p>
        : failed ? <p className="error">{copy.imports.loadFailed}</p>
          : imports.length === 0 ? <p className="import-placeholder">{copy.productPages.import.empty}</p>
            : (
              <div className="import-table-wrap">
                <table className="import-table">
                  <thead><tr>
                    <th>{copy.imports.file}</th><th>{copy.imports.accountName}</th>
                    <th>{copy.imports.period}</th><th>{copy.imports.importedRows}</th>
                    <th>{copy.imports.duplicateRows}</th><th>{copy.imports.status}</th>
                  </tr></thead>
                  <tbody>
                    {imports.map((batch) => (
                      <tr key={batch.id}>
                        <td>{batch.file_name}<small className="event-time">{formatTimestamp(batch.created_at, english ? 'en-US' : 'zh-CN')}</small>{(batch.excluded?.length > 0 || batch.errors.length > 0) && <details><summary>{english ? 'Row report' : '行报告'} · {batch.skipped_rows ?? 0} {english ? 'excluded' : '行排除'}</summary>{[...batch.errors, ...(batch.excluded ?? [])].map((row) => <p key={`${row.row_number}-${row.code}`}>{row.row_number} · {row.message}</p>)}</details>}</td><td>{batch.account_name} · {batch.currency}</td>
                        <td>{batch.start_date && batch.end_date ? `${batch.start_date} — ${batch.end_date}` : '—'}</td>
                        <td>{batch.imported_rows} / {batch.total_rows}</td><td>{batch.duplicate_rows}</td>
                        <td><ImportStatus batch={batch} copy={copy} />{batch.status !== 'REVOKED' && batch.status !== 'REJECTED' && (pending === batch.id ? <div><p>{english ? 'Remove imported transactions? Snapshots remain.' : '撤销本批次交易？保留历史快照。'}</p><button disabled={busy} onClick={() => void revoke(batch)}>{english ? 'Confirm revocation' : '确认撤销'}</button><button disabled={busy} onClick={() => setPending(null)}>{english ? 'Cancel' : '取消'}</button></div> : <button onClick={() => setPending(batch.id)}>{english ? 'Revoke' : '撤销批次'}</button>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
    </section>
  )
}

function ImportStatus({ batch, copy }: { batch: ImportBatch; copy: Messages }) {
  return <span className={`import-status import-status-${batch.status.toLowerCase()}`}>{copy.imports.statuses[batch.status]}</span>
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
