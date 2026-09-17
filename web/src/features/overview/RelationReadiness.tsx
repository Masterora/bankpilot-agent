/** 文件职责：按需检查所选期间待核对关系，避免总览首屏触发昂贵候选扫描。 */
import { useState } from 'react'
import { api } from '../../api'
import { LoadingIndicator } from '../../shared/ui'

export function RelationReadiness({
  start,
  end,
  english,
  onReview,
}: {
  start: string
  end: string
  english: boolean
  onReview: () => void
}) {
  const [result, setResult] = useState<{ count: number; truncated: boolean } | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  return (
    <section className="review-readiness" aria-label={english ? 'Review status' : '核对状态'}>
      <span>
        {result
          ? result.count
            ? english
              ? `${result.count} relationships need review`
              : `${result.count} 项待核对`
            : english
              ? 'No candidates found'
              : '未发现候选'
          : english
            ? 'Relationships unchecked'
            : '本期关系未检查'}
      </span>
      {result?.truncated && (
        <span>
          {english ? 'Search limited; narrow the period' : '候选搜索已达上限，请缩短期间'}
        </span>
      )}
      {failed && (
        <span role="alert">{english ? 'Check failed. Retry.' : '检查失败，请重试。'}</span>
      )}
      {loading ? (
        <LoadingIndicator label={english ? 'Checking relationships' : '正在检查关系'} />
      ) : (
        <button
          onClick={async () => {
            setLoading(true)
            setFailed(false)
            try {
              const data = await api.relations(start, end)
              setResult({
                count: data.items.filter((item) => item.state === 'pending').length,
                truncated: data.truncated,
              })
            } catch {
              setFailed(true)
            } finally {
              setLoading(false)
            }
          }}
        >
          {english ? 'Check candidates' : '检查关系'}
        </button>
      )}
      <button className="text-action" onClick={onReview}>
        {english ? 'Review relationships' : '进入核对'}
      </button>
    </section>
  )
}
