/**
 * 文件职责：组合账单导入页面。
 *
 * 主要内容：渲染文件入口、账户与字段表单、预览、结果、历史和账户列表。
 *
 * 关键边界：业务状态由导入 Hook 管理，页面只组合组件并保持切页状态。
 */

import type { Messages } from '../../i18n'
import { PageHeader } from '../../shared/ui'
import type { ImportBatch, ImportFieldMapping } from '../../types'
import { Accounts } from '../overview/Accounts'
import { ImportHistory, ImportPreviewPanel, ImportReport } from './ImportPanels'
import { useImportWorkflow } from './useImportWorkflow'

interface ImportPageProps {
  copy: Messages
  active: boolean
  english: boolean
  failed: boolean
  imports: ImportBatch[]
  loading: boolean
  onImported: (batch: ImportBatch) => void
  onAnalyze: () => void
  onRetryHistory: () => void
}

export function ImportPage(props: ImportPageProps) {
  const {
    copy, active, english, failed, imports, loading, onImported, onAnalyze, onRetryHistory,
  } = props
  const workflow = useImportWorkflow({ active, copy, english, imports, onImported })
  const {
    accountId, accountName, accounts, accountsFailed, content, currency, detecting, error,
    fileName, headers, mapping, mappingHasDuplicates, preview, previewCurrent, ready,
    result, retryFile, source, submitting,
  } = workflow

  return (
    <section className="product-page">
      <PageHeader copy={copy} page="import" />
      <div className="import-steps" aria-label={english ? 'Import steps' : '导入步骤'}><span>01 {english ? 'Statement' : '选择账单'}</span><span aria-hidden="true">→</span><span>02 {english ? 'Preview' : '预览核对'}</span><span aria-hidden="true">→</span><span>03 {english ? 'Confirm' : '确认入账'}</span></div>

      <form className="import-workspace" onSubmit={workflow.submit}>
        <section className={`import-source-panel${content ? ' has-file' : ''}`}>
          <label className="file-drop">
            <input type="file" accept=".csv,.xlsx" onChange={workflow.selectFile} />
            <span className="file-drop-icon" aria-hidden="true">↑</span>
            <strong>{fileName || copy.imports.chooseFile}</strong>
            <span>{copy.imports.fileRequirements}</span>
          </label>
          {content && <>
            <div className="import-file-state">
              <strong>{source === 'alipay' ? '支付宝' : source === 'wechat' ? '微信支付' : (english ? 'Standard statement' : '标准账单')}</strong>
              <span>{previewCurrent ? (english ? 'Preview ready' : '已完成预览') : (english ? 'Recognized' : '已识别')}</span>
            </div>
            <div className="import-account-grid">
              <label>{english ? 'Import into' : '导入账户'}
                <select value={accountId} disabled={submitting} onChange={(event) => {
                  workflow.setAccountId(event.target.value)
                  const selected = accounts.find((account) => account.id === event.target.value)
                  if (selected) {
                    workflow.setAccountName(selected.name)
                    workflow.setCurrency(selected.currency)
                  } else {
                    workflow.setAccountName('')
                  }
                }}>
                  <option value="">{english ? 'New account' : '新建账户'}</option>
                  {accounts.filter((account) => account.source === source && (!currency || account.currency === currency)).map((account) => <option key={account.id} value={account.id}>{account.name} · {account.currency}</option>)}
                </select>
                {accountsFailed && <span role="alert">{english ? 'Accounts unavailable. Select the file again.' : '账户读取失败，请重新选择文件。'}</span>}
              </label>
              <label>{copy.imports.accountName}
                <input readOnly={Boolean(accountId)} maxLength={100} placeholder={copy.imports.accountPlaceholder} required value={accountName} onChange={(event) => workflow.setAccountName(event.target.value)} />
              </label>
              <label>{copy.imports.currency}
                <input aria-label={copy.imports.currency} readOnly={source !== 'standard' || Boolean(accountId)} inputMode="text" maxLength={3} pattern="[A-Za-z]{3}" placeholder={copy.imports.currencyPlaceholder} required value={currency} onChange={(event) => workflow.setCurrency(event.target.value.replace(/[^A-Za-z]/g, '').toUpperCase())} />
              </label>
            </div>
            {source === 'standard' && <MappingFields copy={copy} english={english} headers={headers} mapping={mapping} onChange={workflow.updateMapping} />}
            {mappingHasDuplicates && <p className="error">{copy.imports.duplicateMapping}</p>}
            <button className="primary import-submit" disabled={!ready || submitting || Boolean(preview && previewCurrent && preview.error_rows > 0)}>
              {submitting && <span className="button-spinner" aria-hidden="true" />}
              {submitting ? copy.imports.importing : previewCurrent ? (english ? 'Confirm import' : '确认导入') : (english ? 'Preview statement' : '预览账单')}
            </button>
          </>}
        </section>
      </form>

      {preview && previewCurrent && <ImportPreviewPanel copy={copy} currency={currency} english={english} preview={preview} />}
      {error && <p className="error import-page-error" role="alert">{error}</p>}
      {detecting && <p role="status">{english ? 'Recognizing statement' : '正在识别账单'}</p>}
      {retryFile && <button type="button" disabled={detecting} onClick={() => void workflow.detectFile(retryFile)}>{english ? 'Retry detection' : '重试识别'}</button>}
      {result && <>
        <ImportReport batch={result} copy={copy} english={english} />
        {result.status !== 'REJECTED' && <div className="import-next"><button type="button" className="primary" onClick={onAnalyze}>{copy.openReview}<span aria-hidden="true"> →</span></button></div>}
      </>}
      {failed && <button type="button" onClick={onRetryHistory}>{english ? 'Retry history' : '重新读取历史'}</button>}
      {(loading || failed || imports.length > 0) && <ImportHistory copy={copy} english={english} failed={failed} imports={imports} loading={loading} onRevoked={onImported} />}
      {active && <Accounts key={imports.map((batch) => `${batch.id}:${batch.status}`).join('|')} english={english} onChanged={() => workflow.setAccountsAttempt((value) => value + 1)} />}
    </section>
  )
}

function MappingFields({ copy, english, headers, mapping, onChange }: {
  copy: Messages
  english: boolean
  headers: string[]
  mapping: ImportFieldMapping
  onChange: (field: keyof ImportFieldMapping, value: string) => void
}) {
  return <details className="mapping-details"><summary>{english ? 'Field mapping' : '字段对应'}</summary><div className="mapping-fields">
    <MappingSelect copy={copy} field="occurredAt" headers={headers} required value={mapping.occurred_at} onChange={(value) => onChange('occurred_at', value)} />
    <MappingSelect copy={copy} field="merchant" headers={headers} required value={mapping.merchant} onChange={(value) => onChange('merchant', value)} />
    <MappingSelect copy={copy} field="amount" headers={headers} required value={mapping.amount} onChange={(value) => onChange('amount', value)} />
    <MappingSelect copy={copy} field="description" headers={headers} value={mapping.description ?? ''} onChange={(value) => onChange('description', value)} />
  </div></details>
}

function MappingSelect({ copy, field, headers, onChange, required = false, value }: {
  copy: Messages
  field: 'occurredAt' | 'merchant' | 'amount' | 'description'
  headers: string[]
  onChange: (value: string) => void
  required?: boolean
  value: string
}) {
  return <label><span>{copy.imports[field]}{required ? ' *' : ''}</span><select required={required} value={value} onChange={(event) => onChange(event.target.value)}><option value="">{required ? copy.imports.selectColumn : copy.imports.notMapped}</option>{headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>
}
