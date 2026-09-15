/**
 * 文件职责：展示月报详情、快照证据与操作确认。
 * 主要内容：状态说明、生成/导出/删除操作、分类和原始证据展示。
 * 关键边界：只展示服务端快照；确认与证据展开状态属于当前报告，不发起后台轮询。
 */
import { useState } from 'react'

import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { ReportDetail } from '../../types'
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
      <h2>{report.month.slice(0, 7)} · {statusLabel}</h2>
      {report.stale && (
        <p role="status" className="scope-note">
          {english
            ? 'The ledger or rules have changed. This report retains its original evidence. Changes may concern another month; regenerate to review the latest state.'
            : '账本或规则已更新，此报告保留原证据。变动可能来自其他月份，可重新生成核对最新状态。'}
        </p>
      )}
      {pending && (
        <p role="status">
          {english
            ? 'The saved task will continue after you leave this page.'
            : '任务已保存，离开页面后仍会继续处理。'}
        </p>
      )}
      {report.status === 'FAILED' && (
        <p role="alert">
          {english
            ? 'Generation failed. Check data availability or the monthly transaction limit (10,000), then generate again.'
            : '生成失败，请检查数据连接或当月交易是否超过 10,000 笔，再重新生成。'}
        </p>
      )}
      <div className="report-toolbar">
        <button disabled={busy || pending} onClick={() => { void onGenerate(report.month.slice(0, 7)) }}>
          {english ? 'Generate new version' : '重新生成新版本'}
        </button>
        <button disabled={report.status !== 'SUCCEEDED'} onClick={() => { void onExport(report.id) }}>
          {english ? 'Export evidence (JSON)' : '导出完整证据（JSON）'}
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
        <>
          <p className="scope-note">
            {english ? 'Ledger revision' : '账本修订号'} {snapshot.ledger_revision} · {snapshot.report_rule_version}
          </p>
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
        </>
      )}
    </article>
  )
}
