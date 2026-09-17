/** 文件职责：人工配对的双边搜索、事实约束和提交预览；服务端裁决版本与关联冲突。 */
import { cents, eligiblePair, conflictFree } from './pairEligibility'
import { useState } from 'react'
import { formatMoney, formatTransactionTime } from '../../format'
import type { RelationKind, RelationTransaction } from '../../types'

export function ManualRelation({
  transactions,
  start,
  end,
  english,
  busy,
  seedId,
  relations,
  onImport,
  onConfirm,
}: {
  relations: import('../../types').TransactionRelation[]
  onImport: () => void
  transactions: RelationTransaction[]
  start: string
  end: string
  english: boolean
  busy: boolean
  seedId?: string
  onConfirm: (kind: RelationKind, first: string, second: string) => Promise<boolean>
}) {
  const seed = transactions.find((row) => row.id === seedId)
  const [kind, setKind] = useState<RelationKind>(
    seed && !seed.amount.startsWith('-') ? 'duplicate' : 'transfer',
  )
  const [first, setFirst] = useState(seed?.id ?? '')
  const [second, setSecond] = useState('')
  const [searches, setSearches] = useState(['', ''])
  const t = (zh: string, en: string) => (english ? en : zh)
  const a = transactions.find((row) => row.id === first)
  const b = transactions.find((row) => row.id === second)
  const touchesPeriod = [a, b].some(
    (row) => row && row.booking_date >= start && row.booking_date <= end,
  )
  const valid =
    a &&
    b &&
    eligiblePair(kind, a, b) &&
    conflictFree(kind, a, b, relations, transactions) &&
    touchesPeriod
  const roles =
    kind === 'duplicate'
      ? [t('保留记录', 'Keep'), t('排除记录', 'Exclude')]
      : [t('原支出记录', 'Original outflow'), t('到账记录', 'Incoming record')]
  return (
    <details className="scope-note" open={!!seedId}>
      <summary>{t('手动关联', 'Link transactions')}</summary>
      <form
        className="manual-relation"
        onSubmit={async (event) => {
          event.preventDefault()
          if (!busy && valid && (await onConfirm(kind, first, second))) {
            setFirst('')
            setSecond('')
            setSearches(['', ''])
          }
        }}
      >
        <label>
          {t('关系类型', 'Type')}
          <select
            value={kind}
            disabled={busy}
            onChange={(event) => {
              setKind(event.target.value as RelationKind)
              setFirst('')
              setSecond('')
            }}
          >
            {(['duplicate', 'transfer', 'refund'] as const).map((value) => (
              <option value={value} key={value}>
                {
                  {
                    duplicate: t('重复记录', 'Duplicate'),
                    transfer: t('本人转账', 'Own transfer'),
                    refund: t('退款', 'Refund'),
                  }[value]
                }
              </option>
            ))}
          </select>
        </label>
        <p>
          {kind === 'duplicate'
            ? t(
                '仅可关联不同导入批次、同币种同金额、相差不超过一天的记录。同批次疑似重复请核对原始账单；两笔真实消费不能排除。',
                'Duplicates require different batches, equal amounts and dates within one day. For same-batch duplicates, check the source statement; distinct purchases cannot be excluded.',
              )
            : kind === 'transfer'
              ? t(
                  '选择不同账户、同币种、等额收支，日期相差不超过三天。',
                  'Select equal opposite amounts in different accounts, same currency and within three days.',
                )
              : t(
                  '先选原消费，再选其后九十天内同币种退款。累计退款不可超过原消费。',
                  'Select the purchase, then a same-currency refund within 90 days. Total refunds cannot exceed the purchase.',
                )}
        </p>
        {kind === 'duplicate' && (
          <button type="button" onClick={onImport}>
            {t(
              '前往导入历史核对或撤销批次，再修正源文件导入',
              'Review or revoke the batch in import history, then import the corrected source',
            )}
          </button>
        )}
        <small>
          {t(
            '已确认关联的冲突组合不列入候选；如需重新配对，请先撤销原关联。',
            'Conflicting confirmed links are excluded. Revoke the existing link before pairing again.',
          )}
        </small>
        {([first, second] as const).map((value, index) => {
          const choices = transactions.filter((row) =>
            index === 0
              ? kind === 'duplicate'
                ? cents(row.amount) !== 0n
                : cents(row.amount) < 0n
              : !!a &&
                eligiblePair(kind, a, row) &&
                conflictFree(kind, a, row, relations, transactions),
          )
          const matches = choices.filter((row) =>
            `${row.booking_date} ${row.account_name} ${row.merchant} ${row.description} ${row.amount}`
              .toLocaleLowerCase()
              .includes(searches[index].toLocaleLowerCase()),
          )
          const visible = matches.slice(0, 200)
          const selected = choices.find((row) => row.id === value)
          const options = selected && !visible.includes(selected) ? [selected, ...visible] : visible
          return (
            <fieldset key={index} disabled={busy || (index === 1 && !a)}>
              <legend>{roles[index]}</legend>
              <label>
                {t('搜索', 'Search')} · {roles[index]}
                <input
                  value={searches[index]}
                  onChange={(event) =>
                    setSearches((current) =>
                      current.map((query, position) =>
                        position === index ? event.target.value : query,
                      ),
                    )
                  }
                  placeholder={t(
                    '商户、账户、金额、日期或备注',
                    'Merchant, account, amount, date or note',
                  )}
                />
              </label>
              <label>
                {roles[index]}
                <select
                  required
                  value={value}
                  onChange={(event) => {
                    if (index === 0) {
                      setFirst(event.target.value)
                      setSecond('')
                    } else setSecond(event.target.value)
                  }}
                >
                  <option value="">{t('选择交易', 'Select a transaction')}</option>
                  {options.map((row) => (
                    <option key={row.id} value={row.id}>
                      {formatTransactionTime(row, english ? 'en-US' : 'zh-CN')} · {row.account_name}{' '}
                      · {row.merchant} · {row.amount} {row.currency} · #
                      {row.source_row_number ?? row.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <small>
                {matches.length}{' '}
                {t('条符合条件；含期间前后九十天', 'eligible; includes 90 days around this period')}
                {matches.length > 200 &&
                  t('，显示前 200 条，请缩小搜索', '; showing 200, refine search')}
              </small>
            </fieldset>
          )
        })}
        {a && b && (
          <section className="relation-pair">
            {[a, b].map((row, index) => (
              <article className="relation-evidence" key={row.id}>
                <small>{roles[index]}</small>
                <strong>
                  {formatMoney(row.amount, row.currency, english ? 'en-US' : 'zh-CN')}
                </strong>
                <span>
                  {row.booking_date} · {row.merchant} · {row.account_name}
                </span>
                <p>{row.description}</p>
              </article>
            ))}
          </section>
        )}
        {a && b && !touchesPeriod && (
          <p role="alert">
            {t(
              '至少一笔交易须在当前期间内。',
              'At least one transaction must fall in this period.',
            )}
          </p>
        )}
        {valid && (
          <p>
            {kind === 'duplicate'
              ? t(
                  '确认后只排除第二笔统计，保留原始流水。',
                  'Exclude only the second record from totals; retain original evidence.',
                )
              : kind === 'transfer'
                ? t(
                    '确认后，两笔不再计入收入和支出。',
                    'Exclude both records from income and spending.',
                  )
                : t(
                    '确认后，退款不再计入收入，冲减到账月份的原消费分类支出。',
                    'Remove refund from income and reduce the purchase category in the receipt month.',
                  )}
          </p>
        )}
        <button disabled={busy || !valid}>{t('确认关联', 'Confirm relation')}</button>
      </form>
    </details>
  )
}
