/**
 * 文件职责：展示月报详情、快照证据与操作确认。
 * 主要内容：状态、生成导出删除、分类与原始证据，以及快照 CSV 转换。
 * 关键边界：仅展示冻结快照；CSV 转义文本并防止公式执行，确认与展开状态属于当前报告。
 */
import { useState } from 'react'

import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { ReportDetail, Transaction } from '../../types'
import { ReportSummary } from './ReportSummary'
import { downloadFile } from '../../shared/download'
import { ReviewSnapshot } from '../agent/ReviewSnapshot'

interface Props {
  report: ReportDetail
  statusLabel: string
  copy: Messages
  locale: Locale
  busy: boolean
  onGenerate: (month: string) => Promise<void>
  onExport: (id: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

export function ReportDetailPanel({
  report, statusLabel, copy, locale, busy, onGenerate, onExport, onDelete,
}: Props) {
  const english = locale === 'en-US'
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [evidenceLimit, setEvidenceLimit] = useState(50)
  const snapshot = report.snapshot
  const pending = report.status === 'QUEUED' || report.status === 'RUNNING'

  return (
    <article className="report-detail">
      {!snapshot && <h2>{report.month.slice(0, 7)} · {statusLabel}</h2>}
      {pending && (
        <p role="status">
          {english
            ? 'Generating in the background…'
            : '后台生成中…'}
        </p>
      )}
      {report.status === 'FAILED' && (
        <p role="alert">
          {english
            ? 'Generation failed. Try generating again.'
            : '生成失败，请重新生成。'}
        </p>
      )}
      {snapshot && <ReportSummary report={report} locale={locale} />}
      <div className="report-toolbar">
        <button disabled={!snapshot} onClick={() => window.print()}>{english ? 'Print / Save PDF' : '打印／保存 PDF'}</button>
        <button disabled={!snapshot} onClick={() => { if (snapshot) downloadFile(ledgerCsv(snapshot.transactions.items), `bankpilot-${report.month.slice(0, 7)}.csv`, 'text/csv;charset=utf-8') }}>{english ? 'Export transactions (CSV)' : '导出流水表格'}</button>
        <button disabled={busy || pending} onClick={() => { void onGenerate(report.month.slice(0, 7)) }}>
          {english ? 'Generate new version' : '重新生成新版本'}
        </button>

        <button disabled={busy} onClick={() => setConfirmDelete(true)}>
          {english ? 'Delete report' : '删除报告'}
        </button>
      </div>
      {confirmDelete && (
        <div className="scope-note" role="group" aria-label={english ? 'Confirm deletion' : '确认删除'}>
          <p>
            {english
              ? 'Delete this report and its saved evidence? This cannot be undone.'
              : '删除此报告及其保存的证据？此操作无法撤销。'}
          </p>
          <div className="report-toolbar">
            <button disabled={busy} onClick={() => { void onDelete(report.id) }}>
              {english ? 'Confirm delete' : '确认删除'}
            </button>
            <button disabled={busy} onClick={() => setConfirmDelete(false)}>
              {english ? 'Cancel' : '取消'}
            </button>
          </div>
        </div>
      )}
      {snapshot && (
        <details className="report-technical"><summary>{english ? 'View calculation and original evidence' : '查看计算过程与原始证据'}</summary>
          <p className="scope-note">
            {english ? 'Ledger revision' : '账本修订号'} {snapshot.ledger_revision} · {snapshot.report_rule_version}
          </p>
                  <button disabled={report.status !== 'SUCCEEDED'} onClick={() => { void onExport(report.id) }}>
          {english ? 'Export evidence (JSON)' : '导出完整证据（JSON）'}
        </button>
          <ReviewSnapshot review={snapshot.review} locale={locale} />
          <details className="scope-note">
            <summary>{english ? 'Raw category totals' : '原始分类汇总'}</summary>
            <p>
              {english
                ? 'These totals use original transactions, before relationship adjustments.'
                : '分类汇总使用原始流水，未应用关系调整。'}
            </p>
            {snapshot.analysis.category_summaries.map((item) => (
              <p key={`${item.currency}:${item.category}`}>
                {copy.categoryLabels[item.category]} · {formatMoney(item.amount, item.currency, locale)}
                {' · '}{item.transaction_count} {english ? 'transactions' : '笔'}
              </p>
            ))}
          </details>
          <details className="scope-note">
            <summary>
              {english ? 'Rule flags (unconfirmed)' : '规则提示（未经确认）'} · {snapshot.analysis.anomalies.length}
            </summary>
            {snapshot.analysis.anomalies.map((item, index) => (
              <div key={index}>
                <p>
                  {item.rule_id === 'large_outflow_v1'
                    ? (english ? 'Large outflow' : '大额支出')
                    : (english ? 'Possible duplicate' : '疑似重复')}
                </p>
                <p>{item.transaction_ids.join(' · ')}</p>
              </div>
            ))}
          </details>
          <details className="scope-note">
            <summary>
              {english ? 'Original transaction evidence' : '原始交易证据'} · {snapshot.transactions.items.length}
            </summary>
            {snapshot.transactions.items.slice(0, evidenceLimit).map((item) => (
              <div className="snapshot-evidence" key={item.id}>
                <strong>
                  {item.booking_date} · {item.merchant} · {formatMoney(item.amount, item.currency, locale)}
                </strong>
                <span>{item.account_name} · {copy.categoryLabels[item.category]}</span>
                <small>{item.id}</small>
                <small>
                  {english ? 'Import batch / row' : '来源批次 / 行'}:
                  {' '}{item.import_batch_id ?? '—'} / {item.source_row_number ?? '—'}
                </small>
              </div>
            ))}
            {snapshot.transactions.items.length > evidenceLimit && (
              <button onClick={() => setEvidenceLimit((value) => value + 50)}>
                {english ? 'Show more evidence' : '显示更多证据'}
              </button>
            )}
          </details>
        </details>
      )}
    </article>
  )
}

/** 文本转义并阻止表格公式执行；金额字段仅接受服务端数字字符串。 */
function ledgerCsv(items: Transaction[]): string {
  const cell = (value: string) => `"${(/^[\s]*[=+@-]/.test(value) ? `'${value}` : value).replaceAll('"', '""')}"`
  return '\ufeff' + ['Date,Time UTC,Precision,Account,Merchant,Amount,Currency,Category,Batch,Source row,Description', ...items.map((i) =>
    [cell(i.booking_date), cell(i.time_precision === 'timestamp' ? new Date(i.occurred_at).toISOString().replace(/\.\d{3}Z$/, 'Z') : ''), cell(i.time_precision ?? 'unknown'), cell(i.account_name), cell(i.merchant), /^-?\d+(\.\d+)?$/.test(i.amount) ? i.amount : cell(i.amount), cell(i.currency), cell(i.category), cell(i.import_batch_id ?? ''), String(i.source_row_number ?? ''), cell(i.description)].join(','))].join('\r\n')
}
