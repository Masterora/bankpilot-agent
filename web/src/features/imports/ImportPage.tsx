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

const MAX_FILE_BYTES = 10 * 1024 * 1024
export function ImportPage({
  copy,
  english,
  failed,
  imports,
  loading,
  onImported,
  onAnalyze,
}: {
  copy: Messages
  english: boolean
  failed: boolean
  imports: ImportBatch[]
  loading: boolean
  onImported: (batch: ImportBatch) => void
  onAnalyze: () => void
}) {
  const [fileName, setFileName] = useState('')
  const selectionSequence = useRef(0)
  const [content, setContent] = useState('')
  const [headers, setHeaders] = useState<string[]>([])
  const [accountName, setAccountName] = useState('')
  const [currency, setCurrency] = useState('CNY')
  const [mapping, setMapping] = useState<ImportFieldMapping>({
    occurred_at: '',
    merchant: '',
    amount: '',
    description: null,
  })
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [preview, setPreview] = useState<{ key: string; total_rows: number; error_rows: number; duplicate_rows: number; errors: { row_number: number; message: string }[]; rows: { row_number: number; date: string; merchant: string; amount: string }[] } | null>(null)
  const payload = { file_name: fileName, content, account_name: accountName.trim(), currency, mapping }
  const payloadKey = JSON.stringify(payload)
  const previewCurrent = preview?.key === payloadKey

  // 文件只在浏览器内读取为文本；清空选择器后仍可重新选择同一文件。
  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    const selection = ++selectionSequence.current
    event.target.value = ''
    setError('')
    setResult(null)
    setFileName('')
    setContent('')
    setHeaders([])
    setMapping({ occurred_at: '', merchant: '', amount: '', description: null })
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError(copy.imports.csvOnly)
      return
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(copy.imports.fileTooLarge)
      return
    }
    let text: string
    try {
      text = await file.text()
    } catch {
      setError(copy.imports.fileReadFailed)
      return
    }
    if (selection !== selectionSequence.current) return
    const detectedHeaders = parseCsvHeaders(text)
    if (detectedHeaders.length === 0) {
      setError(copy.imports.missingHeader)
      return
    }
    let detectedMapping: ImportFieldMapping
    try {
      const detection = await api.detectImport(text)
      if (selection !== selectionSequence.current) return
      detectedMapping = detection.mapping
      if (detection.account_name) setAccountName(detection.account_name)
      if (detection.currency) setCurrency(detection.currency)
    } catch {
      if (selection !== selectionSequence.current) return
      setError(english ? 'This statement format is not supported. Keep the original file.' : '暂不支持该账单格式，请保留原始文件。')
      return
    }
    if (selection !== selectionSequence.current) return
    setFileName(file.name)
    setContent(text)
    setHeaders(detectedHeaders)
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
        <p className="eyebrow">{copy.productPages.import.eyebrow}</p>
        <h1>{copy.productPages.import.title}</h1>
        <p>{copy.productPages.import.description}</p>
      </header>
      <details className="import-report"><summary>{english ? 'Supported files' : '支持的文件与获取方式'}</summary><p>{english ? 'Upload a CSV exported by your provider. Institution-specific Excel, PDF and encrypted archives require a verified adapter. Do not convert or edit your bank statement to fit this form.' : '上传机构导出的 CSV。机构专用 Excel、PDF 和加密压缩包需经过格式验证后接入，请勿为适配此表单修改原账单。'}</p></details>

      <form className="import-workspace" onSubmit={submit}>
        <section className="import-source-panel">
          <label className="file-drop">
            <input type="file" accept=".csv,text/csv" onChange={selectFile} />
            <span className="file-drop-icon" aria-hidden="true">↑</span>
            <strong>{fileName || copy.imports.chooseFile}</strong>
            <span>{copy.imports.fileRequirements}</span>
          </label>
          <div className="import-account-grid">
            <label>
              {copy.imports.accountName}
              <input
                maxLength={100}
                placeholder={copy.imports.accountPlaceholder}
                required
                value={accountName}
                onChange={(event) => setAccountName(event.target.value)}
              />
            </label>
            <label>
              {copy.imports.currency}
              <input
                aria-label={copy.imports.currency}
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
          ) : (
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
      {previewCurrent && <section className="import-report"><h2>{english ? 'Import preview' : '导入预览'}</h2><p>{preview.total_rows} {english ? 'rows' : '行'} · {preview.duplicate_rows} {english ? 'duplicates' : '行重复'} · {preview.error_rows} {english ? 'invalid rows' : '行格式异常'}</p>{preview.error_rows > 0 && <p role="alert">{english ? 'This format cannot be imported. Check the field selection or use a supported source file.' : '该格式无法导入。请核对字段选择，或使用已适配的来源文件。'}</p>}<ul>{preview.errors?.map((item) => <li key={item.row_number}>{english ? 'Row' : '第'} {item.row_number}: {item.message}</li>)}</ul><p>{english ? 'First 20 rows; duplicates are checked on confirmation.' : '展示前 20 行；确认导入时检查重复记录。'}</p><div className="import-table-wrap"><table className="import-table"><tbody>{preview.rows.map((row) => <tr key={row.row_number}><td>{row.date}</td><td>{row.merchant}</td><td>{row.amount} {currency}</td></tr>)}</tbody></table></div></section>}

      {error && <p className="error import-page-error" role="alert">{error}</p>}
      {result && <>
        <ImportReport batch={result} copy={copy} />
        {result.status !== 'REJECTED' && <div className="import-next"><button type="button" className="primary" onClick={onAnalyze}>{copy.openAgent}<span aria-hidden="true"> →</span></button></div>}
      </>}
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

function ImportReport({ batch, copy }: { batch: ImportBatch; copy: Messages }) {
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
      </div>
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
                        <td>{batch.file_name}</td><td>{batch.account_name} · {batch.currency}</td>
                        <td>{batch.start_date && batch.end_date ? `${batch.start_date} — ${batch.end_date}` : '—'}</td>
                        <td>{batch.imported_rows} / {batch.total_rows}</td><td>{batch.duplicate_rows}</td>
                        <td><ImportStatus batch={batch} copy={copy} />{batch.status !== 'REVOKED' && batch.status !== 'REJECTED' && (pending === batch.id ? <div><p>{english ? 'Remove transactions written by this batch? Historical reports remain unchanged.' : '移除本批次写入的交易？历史分析快照保持不变。'}</p><button disabled={busy} onClick={() => void revoke(batch)}>{english ? 'Confirm revocation' : '确认撤销'}</button><button disabled={busy} onClick={() => setPending(null)}>{english ? 'Cancel' : '取消'}</button></div> : <button onClick={() => setPending(batch.id)}>{english ? 'Revoke' : '撤销批次'}</button>)}</td>
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

function parseCsvHeaders(content: string) {
  // 此处仅为映射界面提取首行；完整 CSV 结构由服务端重新解析和校验。
  const firstLine = content.replace(/^\ufeff/, '').split(/\r?\n/, 1)[0] ?? ''
  if (!firstLine.trim()) return []
  const delimiters = [',', ';', '\t']
  const delimiter = delimiters.reduce((best, candidate) =>
    countUnquoted(firstLine, candidate) > countUnquoted(firstLine, best) ? candidate : best)
  return parseDelimitedLine(firstLine, delimiter).map((value) => value.trim()).filter(Boolean)
}

function countUnquoted(line: string, delimiter: string) {
  let quoted = false
  let count = 0
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] === '"') {
      if (quoted && line[index + 1] === '"') index += 1
      else quoted = !quoted
    } else if (!quoted && line[index] === delimiter) count += 1
  }
  return count
}

function parseDelimitedLine(line: string, delimiter: string) {
  const values: string[] = []
  let current = ''
  let quoted = false
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index]
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"'
        index += 1
      } else quoted = !quoted
    } else if (!quoted && character === delimiter) {
      values.push(current)
      current = ''
    } else current += character
  }
  values.push(current)
  return values
}
