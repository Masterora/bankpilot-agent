/**
 * 文件职责：提供账单导入结果展示组件。
 *
 * 主要内容：包含预览、批次报告、历史表格、状态和撤销确认。
 *
 * 关键边界：撤销失败保留当前列表与确认状态，不在组件中计算导入结果。
 */

import { useState } from 'react'

import { api } from '../../api'
import { formatTimestamp, formatTransactionTime } from '../../format'
import type { Messages } from '../../i18n'
import { EmptyContent, LoadingIndicator } from '../../shared/ui'
import type { ImportBatch } from '../../types'
import type { ImportPreview } from './useImportWorkflow'

export function ImportPreviewPanel({
  copy,
  currency,
  english,
  preview,
}: {
  copy: Messages
  currency: string
  english: boolean
  preview: ImportPreview
}) {
  const readyRows = preview.new_rows
  return (
    <section className="import-report">
      <div className="import-panel-heading"><h2>{english ? 'Preview' : '导入预览'}</h2><strong>{readyRows} / {preview.total_rows}</strong></div>
      <div className="import-metrics">
        <Metric label={english ? 'Ready' : '可导入'} value={readyRows} />
        <Metric label={copy.imports.duplicateRows} value={preview.duplicate_rows} />
        <Metric label={english ? 'Excluded' : '排除'} value={preview.skipped_rows} />
        <Metric label={copy.imports.errorRows} value={preview.error_rows} />
      </div>
      {preview.error_rows > 0 && <p className="error" role="alert">{english ? 'Fix invalid rows before importing.' : '请先处理格式异常。'}</p>}
      {preview.excluded.length > 0 && <details><summary>{english ? 'Excluded rows' : '排除明细'}</summary>{preview.excluded.map((item) => <p key={`${item.row_number}-${item.code}`}>{item.row_number} · {item.message}</p>)}</details>}
      {preview.errors.length > 0 && <ul className="import-errors">{preview.errors.map((item) => <li key={`${item.row_number}-${item.code}`}><strong>{english ? 'Row' : '第'} {item.row_number}</strong><span>{item.message}</span></li>)}</ul>}
      {(preview.issues_truncated || preview.excluded_truncated || preview.preview_truncated) && <p className="muted">{english ? 'Showing a limited preview; totals include all rows.' : '仅展示部分明细，统计包含全部行。'}</p>}
      <p>{english ? 'New income / expense / net' : '预计新增收入 / 支出 / 净额'}：{preview.new_amounts.income} / {preview.new_amounts.expense} / {preview.new_amounts.net} {currency}</p>
      <div className="import-table-wrap"><table className="import-table"><thead><tr><th>{english ? 'Time' : '时间'}</th><th>{english ? 'Merchant' : '交易对方'}</th><th>{english ? 'Amount' : '金额'}</th><th>{english ? 'Result' : '处理'}</th></tr></thead><tbody>{preview.rows.map((row) => <tr key={row.row_number}><td>{formatTransactionTime({ booking_date: row.date, occurred_at: row.occurred_at, time_precision: row.time_precision }, english ? 'en-US' : 'zh-CN')}</td><td>{row.merchant}</td><td>{row.amount} {currency}</td><td>{row.classification === 'new' ? (english ? 'New' : '新增') : (english ? 'Duplicate' : '重复')}</td></tr>)}</tbody></table></div>
    </section>
  )
}

export function ImportReport({ batch, copy, english }: { batch: ImportBatch; copy: Messages; english: boolean }) {
  return (
    <section className="import-report" aria-live="polite">
      <div className="import-panel-heading"><h2>{copy.imports.reportHeading}</h2><ImportStatus batch={batch} copy={copy} /></div>
      <div className="import-metrics">
        <Metric label={copy.imports.totalRows} value={batch.total_rows} />
        <Metric label={copy.imports.importedRows} value={batch.imported_rows} />
        <Metric label={copy.imports.duplicateRows} value={batch.duplicate_rows} />
        <Metric label={copy.imports.errorRows} value={batch.error_rows} />
        <Metric label={english ? 'Excluded' : '排除'} value={batch.skipped_rows} />
      </div>
      {(batch.issues_truncated || batch.excluded_truncated) && <p className="muted">{english ? 'Details truncated; totals are complete.' : '明细已截断，计数为全部结果。'}</p>}
      {batch.parser_version === null && <p className="muted">{english ? 'Historical statistics were not recorded.' : '历史规则版本及新增统计未记录。'}</p>}
      {batch.excluded?.length > 0 && <details><summary>{english ? 'Excluded rows' : '排除明细'}</summary>{batch.excluded.map((row) => <p key={row.row_number}>{row.row_number} · {row.message}</p>)}</details>}
      {batch.errors.length > 0 && <ol className="import-errors">{batch.errors.map((item) => <li key={`${item.row_number}-${item.code}`}><strong>{copy.imports.row} {item.row_number}</strong><span>{copy.imports.errorCodes[item.code] ?? item.message}</span></li>)}</ol>}
    </section>
  )
}

export function ImportHistory({
  copy,
  english,
  failed,
  imports,
  loading,
  onRevoked,
  onAnalyze,
}: {
  copy: Messages
  english: boolean
  failed: boolean
  imports: ImportBatch[]
  loading: boolean
  onRevoked: (batch: ImportBatch) => void
  onAnalyze: (batch: ImportBatch) => void
}) {
  const [pending, setPending] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  async function revoke(batch: ImportBatch) {
    setBusy(true)
    setError(false)
    try {
      await api.revokeImport(batch.id)
      onRevoked({ ...batch, status: 'REVOKED' })
      setPending(null)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="import-history">
      <div className="import-panel-heading"><h2>{copy.imports.historyHeading}</h2></div>
      {error && <p role="alert">{english ? 'Revocation failed. Retry.' : '撤销失败，请重试。'}</p>}
      {loading ? <LoadingIndicator label={copy.imports.loading} />
        : failed ? <p className="error">{copy.imports.loadFailed}</p>
          : imports.length === 0 ? <EmptyContent kind="import" title={english ? 'No import history' : '暂无导入记录'} detail={english ? 'Imported files and their processing results will appear here.' : '导入后的文件、处理结果和来源记录会保存在这里。'} />
            : <div className="import-table-wrap"><table className="import-table"><thead><tr><th>{copy.imports.file}</th><th>{copy.imports.accountName}</th><th>{copy.imports.period}</th><th>{copy.imports.importedRows}</th><th>{copy.imports.duplicateRows}</th><th>{copy.imports.status}</th></tr></thead><tbody>{imports.map((batch) => <tr key={batch.id}><td>{batch.file_name}<small className="event-time">{formatTimestamp(batch.created_at, english ? 'en-US' : 'zh-CN')}</small>{(batch.excluded?.length > 0 || batch.errors.length > 0) && <details><summary>{english ? 'Row report' : '行报告'} · {batch.skipped_rows ?? '—'} {english ? 'excluded' : '行排除'}</summary>{[...batch.errors, ...(batch.excluded ?? [])].map((row) => <p key={`${row.row_number}-${row.code}`}>{row.row_number} · {row.message}</p>)}</details>}</td><td>{batch.account_name} · {batch.currency}</td><td>{batch.start_date && batch.end_date ? `${batch.start_date} — ${batch.end_date}` : '—'}</td><td>{batch.imported_rows} / {batch.total_rows}</td><td>{batch.duplicate_rows}</td><td><ImportStatus batch={batch} copy={copy} />{batch.status !== 'REVOKED' && batch.imported_rows > 0 && batch.start_date && batch.end_date && <button onClick={() => onAnalyze(batch)}>{english ? 'View this batch' : '查看本批流水'}</button>}{batch.status !== 'REVOKED' && batch.status !== 'REJECTED' && (pending === batch.id ? <div><p>{english ? 'Remove imported transactions? Snapshots remain.' : '撤销本批次交易？保留历史快照。'}</p><button disabled={busy} onClick={() => void revoke(batch)}>{english ? 'Confirm revocation' : '确认撤销'}</button><button disabled={busy} onClick={() => setPending(null)}>{english ? 'Cancel' : '取消'}</button></div> : <button onClick={() => setPending(batch.id)}>{english ? 'Revoke' : '撤销批次'}</button>)}</td></tr>)}</tbody></table></div>}
    </section>
  )
}

function Metric({ label, value }: { label: string; value: number | null }) {
  return <div><span>{label}</span><strong>{value ?? '—'}</strong></div>
}

function ImportStatus({ batch, copy }: { batch: ImportBatch; copy: Messages }) {
  return <span className={`import-status import-status-${batch.status.toLowerCase()}`}>{batch.imported_rows === 0 && (batch.status === 'COMPLETED' || batch.status === 'COMPLETED_WITH_DUPLICATES') ? `${copy.imports.importedRows} 0` : copy.imports.statuses[batch.status]}</span>
}
