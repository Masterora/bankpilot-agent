/** Reusable limits, frozen preview and explicit confirmation; no browser arithmetic. */
import { useEffect, useRef, useState } from 'react'
import { newIdempotencyKey } from '../../shared/operationKey'
import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Locale, Messages } from '../../i18n'
import type { TransactionCategory } from '../../types'
import { planningError } from './errors'
import type { BudgetTemplate, BudgetTemplateEntry, BudgetWorkspace, TemplatePreview } from './types'
import type { PlanningState } from './usePlanningMonth'

export function BudgetTemplates({
  state,
  copy,
  locale,
  disabled,
  externalRevision,
  onDirty,
}: {
  state: PlanningState<BudgetWorkspace>
  copy: Messages
  locale: Locale
  disabled: boolean
  externalRevision: number
  onDirty: (dirty: boolean) => void
}) {
  const english = locale === 'en-US'
  const t = (zh: string, en: string) => (english ? en : zh)
  const [items, setItems] = useState<BudgetTemplate[]>([])
  const [draft, setDraft] = useState<Omit<BudgetTemplate, 'version'> | null>(null)
  const [selected, setSelected] = useState('')
  const [mode, setMode] = useState<'missing' | 'overwrite'>('missing')
  const [preview, setPreview] = useState<TemplatePreview | null>(null)
  const [attempt, setAttempt] = useState<{ preview: TemplatePreview; id: string } | null>(null)
  const [deleteId, setDeleteId] = useState<BudgetTemplate | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [retry, setRetry] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const generation = useRef(0)
  const writing = useRef(false)
  useEffect(() => {
    onDirty(draft !== null || attempt !== null || busy)
  }, [draft, attempt, busy, onDirty])
  useEffect(() => {
    const requests = generation
    const token = ++requests.current
    setListLoading(true)
    setPreview((current) =>
      current?.applied && current.month.slice(0, 7) === state.month ? current : null,
    )
    api
      .budgetTemplates()
      .then((rows) => {
        if (token === generation.current) setItems(rows)
      })
      .catch((e) => {
        if (token === generation.current) setError(planningError(e, english))
      })
      .finally(() => {
        if (token === requests.current) setListLoading(false)
      })
    return () => {
      requests.current++
    }
  }, [state.month, externalRevision, retry, english])
  const locked = disabled || busy
  async function run(action: () => Promise<void>) {
    if (writing.current || disabled) return
    writing.current = true
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
    } catch (e) {
      setError(planningError(e, english))
    } finally {
      writing.current = false
      setBusy(false)
    }
  }
  function changeEntry(index: number, values: Partial<BudgetTemplateEntry>) {
    if (!draft) return
    setDraft({
      ...draft,
      entries: draft.entries.map((entry, i) => (i === index ? { ...entry, ...values } : entry)),
    })
  }
  return (
    <details className="budget-templates">
      <summary>{t('预算模板', 'Budget templates')}</summary>
      {error && (
        <p role="alert">
          {error}{' '}
          <button
            disabled={locked}
            onClick={() => {
              setError('')
              setRetry((v) => v + 1)
            }}
          >
            {t('刷新模板', 'Refresh templates')}
          </button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <p>
        {t(
          '模板只保存额度。另存本月时，当前额度中的结转金额也会复制。',
          'Templates store limits only. Saving this month also copies any amounts already carried into those limits.',
        )}
      </p>
      <button
        disabled={locked || !!draft || !!attempt || !state.data?.items.length}
        onClick={() => {
          setDraft({
            id: newIdempotencyKey(),
            name: '',
            expected_version: 0,
            entries: state.data!.items.map(({ category, currency, amount }) => ({
              category,
              currency,
              amount,
            })),
          })
          setPreview(null)
        }}
      >
        {t('将本月额度另存为模板', 'Save this month as template')}
      </button>
      <button
        disabled={locked || !!draft || !!attempt}
        onClick={() => {
          setDraft({
            id: newIdempotencyKey(),
            name: '',
            expected_version: 0,
            entries: [{ category: 'dining', currency: 'CNY', amount: '100.00' }],
          })
          setPreview(null)
        }}
      >
        {t('新建模板', 'New template')}
      </button>
      {listLoading && <p role="status">{t('正在读取模板…', 'Loading templates…')}</p>}
      {!listLoading && !error && !items.length && <p>{t('暂无模板', 'No templates')}</p>}
      {!!items.length && (
        <div className="report-toolbar">
          <label>
            {t('选择模板', 'Template')}
            <select
              value={selected}
              disabled={locked || !!draft || !!attempt}
              onChange={(e) => {
                setSelected(e.target.value)
                setPreview(null)
                setDeleteId(null)
              }}
            >
              <option value="">{t('请选择', 'Select')}</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · v{item.version}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('应用方式', 'Apply mode')}
            <select
              value={mode}
              disabled={locked || !!draft || !!attempt}
              onChange={(e) => {
                setMode(e.target.value as typeof mode)
                setPreview(null)
              }}
            >
              <option value="missing">{t('仅补缺项', 'Missing only')}</option>
              <option value="overwrite">
                {t('覆盖模板中的已有额度', 'Replace matching limits')}
              </option>
            </select>
          </label>
          <button
            disabled={locked || listLoading || !selected || !!draft || !!attempt}
            onClick={() =>
              void run(async () =>
                setPreview(await api.previewBudgetTemplate(selected, state.month, mode)),
              )
            }
          >
            {t('预览应用', 'Preview application')}
          </button>
          <button
            disabled={locked || listLoading || !selected || !!draft || !!attempt}
            onClick={() => {
              const item = items.find((i) => i.id === selected)
              if (item) {
                setDraft({
                  id: item.id,
                  name: item.name,
                  expected_version: item.version,
                  entries: item.entries.map((e) => ({ ...e })),
                })
                setPreview(null)
              }
            }}
          >
            {t('编辑模板', 'Edit template')}
          </button>
          <button
            disabled={locked || listLoading || !selected || !!draft || !!attempt}
            onClick={() => {
              setDeleteId(items.find((i) => i.id === selected) ?? null)
              setPreview(null)
            }}
          >
            {t('删除模板', 'Delete template')}
          </button>
        </div>
      )}
      {deleteId && (
        <div className="planning-confirm">
          <p>
            {t(
              `删除模板“${deleteId.name}”？已经应用的月份不受影响。`,
              `Delete “${deleteId.name}”? Applied months are retained.`,
            )}
          </p>
          <button
            disabled={locked}
            onClick={() =>
              void run(async () => {
                await api.deleteBudgetTemplate(deleteId.id, deleteId.version)
                setDeleteId(null)
                setSelected('')
                setRetry((v) => v + 1)
              })
            }
          >
            {t('确认删除模板', 'Confirm deletion')}
          </button>
          <button disabled={locked} onClick={() => setDeleteId(null)}>
            {t('取消', 'Cancel')}
          </button>
        </div>
      )}
      {draft && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              const result = await api.saveBudgetTemplate(draft)
              generation.current++
              setListLoading(false)
              setItems((rows) => [...rows.filter((r) => r.id !== result.id), result])
              setSelected(result.id)
              setDraft(null)
              setNotice(t('模板已保存', 'Template saved'))
            })
          }}
        >
          <label>
            {t('模板名称', 'Template name')}
            <input
              required
              maxLength={80}
              value={draft.name}
              disabled={locked}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          {!listLoading &&
            draft.expected_version > 0 &&
            items.find((item) => item.id === draft.id)?.version !== draft.expected_version && (
              <div className="planning-confirm">
                <p>
                  {t(
                    '模板已变化；刷新后核对当前模板，再明确选择使用最新版本保存草稿。',
                    'Template changed. Refresh and review it before saving this draft against its latest version.',
                  )}
                </p>
                {items
                  .find((item) => item.id === draft.id)
                  ?.entries.map((entry) => (
                    <p key={`${entry.category}:${entry.currency}`}>
                      {copy.categoryLabels[entry.category]} · {entry.currency} ·{' '}
                      {formatMoney(entry.amount, entry.currency, locale)}
                    </p>
                  ))}
                {items.find((item) => item.id === draft.id) ? (
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() => {
                      setDraft({
                        ...draft,
                        expected_version: items.find((item) => item.id === draft.id)!.version,
                      })
                      setError('')
                    }}
                  >
                    {t('使用最新版本重新确认保存', 'Use latest version and confirm again')}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() =>
                      setDraft({ ...draft, id: newIdempotencyKey(), expected_version: 0 })
                    }
                  >
                    {t('另存为新模板', 'Save as a new template')}
                  </button>
                )}
              </div>
            )}
          {draft.entries.map((entry, index) => (
            <div className="report-toolbar" key={index}>
              <label>
                {t('分类', 'Category')}
                <select
                  disabled={locked}
                  value={entry.category}
                  onChange={(e) =>
                    changeEntry(index, { category: e.target.value as TransactionCategory })
                  }
                >
                  {Object.entries(copy.categoryLabels)
                    .filter(([key]) => key !== 'income')
                    .map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                {t('币种', 'Currency')}
                <input
                  required
                  pattern="[A-Z]{3}"
                  maxLength={3}
                  disabled={locked}
                  value={entry.currency}
                  onChange={(e) => changeEntry(index, { currency: e.target.value.toUpperCase() })}
                />
              </label>
              <label>
                {t('额度', 'Limit')}
                <input
                  required
                  type="number"
                  min="0.01"
                  step="0.01"
                  max="9999999999999999.99"
                  disabled={locked}
                  value={entry.amount}
                  onChange={(e) => changeEntry(index, { amount: e.target.value })}
                />
              </label>
              <button
                type="button"
                disabled={locked || draft.entries.length === 1}
                onClick={() =>
                  setDraft({ ...draft, entries: draft.entries.filter((_, i) => i !== index) })
                }
              >
                {t('移除额度', 'Remove limit')}
              </button>
            </div>
          ))}
          <button
            type="button"
            disabled={locked || draft.entries.length >= 100}
            onClick={() =>
              setDraft({
                ...draft,
                entries: [
                  ...draft.entries,
                  { category: 'dining', currency: 'CNY', amount: '100.00' },
                ],
              })
            }
          >
            {t('添加额度', 'Add limit')}
          </button>
          <button disabled={locked}>{t('保存模板', 'Save template')}</button>
          <button
            type="button"
            disabled={locked}
            onClick={() => {
              setDraft(null)
              setError('')
            }}
          >
            {t('放弃编辑', 'Discard draft')}
          </button>
        </form>
      )}
      {(preview || attempt) && (
        <div className="planning-confirm">
          <p>
            {(attempt?.preview ?? preview)!.template_name} → {state.month} ·{' '}
            {t('不删除模板之外的预算', 'Other budgets are retained')}
          </p>
          {(attempt?.preview ?? preview)!.changes.map((row) => (
            <p key={`${row.category}:${row.currency}`}>
              {copy.categoryLabels[row.category]} · {row.currency} ·{' '}
              {row.before === null ? '—' : formatMoney(row.before, row.currency, locale)} →{' '}
              {formatMoney(row.after, row.currency, locale)} ·{' '}
              {row.action === 'keep'
                ? t('保留', 'Keep')
                : row.action === 'create'
                  ? t('新增', 'Create')
                  : t('覆盖', 'Replace')}
            </p>
          ))}
          {preview?.applied ? (
            <p role="status">
              {t('已应用；以上为当时回执', 'Applied; these are the frozen receipt values')}
            </p>
          ) : (
            <>
              <button
                disabled={locked}
                onClick={() =>
                  void run(async () => {
                    const pending = attempt ?? { preview: preview!, id: newIdempotencyKey() }
                    setAttempt(pending)
                    let receipt: TemplatePreview | null = null
                    const applied = await state.perform(async () => {
                      receipt = await api.applyBudgetTemplate(pending.preview, pending.id)
                    })
                    if (applied) {
                      setAttempt(null)
                      setPreview(receipt)
                    }
                  })
                }
              >
                {attempt
                  ? t('按原请求重试', 'Retry original request')
                  : t('确认应用到本月', 'Confirm application')}
              </button>
              {!attempt && (
                <button disabled={locked} onClick={() => setPreview(null)}>
                  {t('取消应用', 'Cancel')}
                </button>
              )}
              {attempt && (
                <button
                  disabled={locked}
                  onClick={() =>
                    void run(async () => {
                      setAttempt(null)
                      setPreview(null)
                      setRetry((v) => v + 1)
                      await state.refresh()
                    })
                  }
                >
                  {t('核对当前预算并重新预览', 'Review current budgets and preview again')}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </details>
  )
}
