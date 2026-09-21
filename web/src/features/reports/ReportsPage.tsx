/**
 * 文件职责：编排月报工作区页面。
 * 主要内容：月份表单、历史列表、分页与当前报告选择。
 * 关键边界：请求状态由 useReports 管理，详情与证据由 ReportDetailPanel 展示。
 */
import type { FormEvent } from 'react'

import { formatTimestamp } from '../../format'
import type { Locale, Messages } from '../../i18n'
import { IconButton, LoadingIndicator, PageHeader } from '../../shared/ui'
import { ReportComparison } from './ReportComparison'
import { ReportDetailPanel } from './ReportDetailPanel'
import { useReports } from './useReports'

const statusLabels = {
  QUEUED: ['等待生成', 'Queued'], RUNNING: ['生成中', 'Generating'],
  SUCCEEDED: ['已生成', 'Ready'], FAILED: ['生成失败', 'Failed'], DELETED: ['已删除', 'Deleted'],
}

interface Props {
  copy: Messages
  locale: Locale
  initialMonth: string
  active: boolean
}

export function ReportsPage({ copy, locale, initialMonth, active }: Props) {
  const english = locale === 'en-US'
  const {
    month, setMonth, items, offset, goToPage, hasMore, selected, detail,
    listError, detailError, loading, busy, error,
    selectReport, generate, remove, exportReport, refreshReports,
  } = useReports(initialMonth, english, active)

  const previous = detail && items.find((item) => item.month === detail.month && item.created_at < detail.created_at && item.status === 'SUCCEEDED')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void generate(month)
  }

  return (
    <section className="product-page reports-page">
      <PageHeader copy={copy} page="reports" />
      <form className="report-toolbar" onSubmit={submit}>
        <label>
          {english ? 'Month' : '统计月份'}
          <input
            type="month" min="1900-01" max="9998-12" required value={month}
            disabled={busy} onChange={(event) => setMonth(event.target.value)}
          />
        </label>
        <button className="primary" aria-busy={busy} disabled={busy || !month}>
          {busy
            ? (english ? 'Submitting…' : '提交中…')
            : (english ? 'Generate report' : '生成月报')}
        </button>
        <IconButton icon="refresh" label={english ? 'Refresh' : '刷新'} disabled={loading || busy} onClick={refreshReports} />
      </form>
      {error && <p role="alert">{error}</p>}
      {listError && (
        <p role="alert">
          {english
            ? 'Could not refresh reports. Existing results are retained.'
            : '报告列表刷新失败，已保留现有结果。'}
        </p>
      )}
      {loading && <LoadingIndicator label={english ? 'Loading reports' : '正在读取报告'} />}
      {!loading && !listError && !items.length && (
        <p>
          {english
            ? 'No reports yet. Select a month to generate one.'
            : '暂无报告，选择月份生成第一份月报。'}
        </p>
      )}
      {detailError && (
        <p role="alert">
          {english ? 'Could not refresh this report. Retry with Refresh.' : '报告读取失败，请点击刷新重试。'}
        </p>
      )}
      {selected && !detail && !detailError && (
        <LoadingIndicator label={english ? 'Loading report' : '正在读取报告'} />
      )}
      <div className="report-columns"><div className="report-main">
      {detail?.id === selected && (
        <ReportDetailPanel
          key={detail.id} report={detail} statusLabel={statusLabels[detail.status][english ? 1 : 0]}
          copy={copy} locale={locale} busy={busy}
          onGenerate={generate} onExport={exportReport} onDelete={remove}
        />
      )}
      {detail?.id === selected && detail.snapshot && previous && <ReportComparison key={`${detail.id}:${previous.id}`} current={detail} previous={previous} locale={locale} />}
      </div><details className="report-history" open><summary>{english ? 'Report versions & history' : '报告版本与历史'}</summary>
      <div className="report-list" aria-label={english ? 'Report history' : '报告历史'}>
        {items.map((item) => (
          <button
            type="button" className="report-list-item" key={item.id}
            aria-pressed={selected === item.id} disabled={busy} onClick={() => selectReport(item.id)}
          >
            <strong>{item.month.slice(0, 7)}{selected === item.id ? (english ? ' · Viewing' : ' · 正在查看') : ''}</strong>
            <span>{statusLabels[item.status][english ? 1 : 0]} · {offset === 0 && items.find((row) => row.month === item.month)?.id === item.id ? (english ? 'Latest version' : '最新版本') : (english ? 'Saved version' : '历史版本')}</span>
            <small>{formatTimestamp(item.created_at, locale)}</small>
            {item.stale && <span>{english ? 'Ledger or rules updated' : '账本或规则已更新'}</span>}
          </button>
        ))}
      </div>
      <div className="report-toolbar">
        <button disabled={!offset || busy || loading} onClick={() => goToPage(Math.max(0, offset - 20))}>
          {english ? 'Previous' : '上一页'}
        </button>
        <span>{english ? 'Page' : '第'} {offset / 20 + 1} {english ? '' : '页'}</span>
        <button disabled={!hasMore || busy || loading} onClick={() => goToPage(offset + 20)}>
          {english ? 'Next' : '下一页'}
        </button>
      </div>
      </details></div>
    </section>
  )
}
