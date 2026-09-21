/**
 * 文件职责：管理持久会话历史、轮次提交及同请求恢复。
 * 主要内容：会话列表和选择、轮次查询、待确认请求身份保存、上下文更新及删除。
 * 关键边界：状态按用户与视图隔离；恢复查询原请求，不自动重放写入，退出后迟到结果不得重建恢复状态。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import type { SearchFilters } from '../ledger/search'
import type { Conversation, SavedTurn, SpendingScope, TurnInput } from './types'

export function useConversations(userId: string, open: boolean, initialMonth: string) {
  const [items, setItems] = useState<Conversation[]>([])
  const [turns, setTurns] = useState<SavedTurn[]>([])
  const [id, setId] = useState<string | null>(null)
  const [searchContext, setSearchContext] = useState<SearchFilters | null>(null)
  const [contextVersion, setContextVersion] = useState(0)
  const [searchUnsaved, setSearchUnsaved] = useState(false)
  const contextEpoch = useRef(0)
  const [scope, setScope] = useState<SpendingScope | null>(null)
  const [month, setMonth] = useState(`${initialMonth.slice(0, 7)}-01`)
  const [cursor, setCursor] = useState<string | null>(null)
  const [before, setBefore] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [limit, setLimit] = useState(200)
  const [unknown, setUnknown] = useState<TurnInput | null>(null)
  const [storageFailed, setStorageFailed] = useState(() => {
    try {
      const probe = `assistant-probe:${userId}`
      sessionStorage.setItem(probe, '1'); sessionStorage.removeItem(probe)
      return false
    } catch { return true }
  })
  const [error, setError] = useState<unknown>(null)
  const epoch = useRef(0)
  const active = useRef<string | null>(null)
  const alive = useRef(true)
  const recovery = useRef<TurnInput | null>(null)
  const key = `assistant:${userId}`
  const currentKey = `assistant-current:${userId}`
  const saveRecovery = useCallback((payload: TurnInput | null) => {
    recovery.current = payload
    setUnknown(payload)
    try {
      if (payload) sessionStorage.setItem(key, JSON.stringify(payload))
      else sessionStorage.removeItem(key)
    } catch { setStorageFailed(true) }
  }, [key])
  const list = useCallback(async (next?: string) => {
    const result = await api.assistantHistory(next)
    if (!alive.current) return result
    setItems(old => next ? [...old, ...result.items.filter(item => !old.some(existing => existing.id === item.id))] : result.items)
    setCursor(result.next_cursor)
    return result
  }, [])
  const load = useCallback(async (target: string, earlier?: number) => {
    const version = ++epoch.current
    contextEpoch.current++
    active.current = target
    setId(target)
    if (!earlier) setTurns([])
    setLoading(true)
    setError(null)
    let result
    try { result = await api.assistantConversation(target, earlier) }
    catch (cause) {
      if (alive.current && epoch.current === version) { setLoading(false); active.current = null; setId(null); setScope(null) }
      throw cause
    }
    if (!alive.current || epoch.current !== version) return
    setLoading(false)
    setTurns(old => earlier ? [...result.turns, ...old] : result.turns)
    setScope(result.conversation.scope)
    setSearchContext(result.conversation.search_context)
    setContextVersion(result.conversation.context_version)
    setSearchUnsaved(false)
    setMonth(result.conversation.month)
    setBefore(result.next_before)
    setLimit(result.turn_limit)
    try { sessionStorage.setItem(currentKey, target) } catch { setStorageFailed(true) }
  }, [currentKey])
  const invalidate = useCallback(() => { epoch.current++ }, [])
  useEffect(() => {
    alive.current = true
    let cancelled = false
    void (async () => {
      let stored: string | null = null
      try {
        stored = sessionStorage.getItem(currentKey)
        const raw = sessionStorage.getItem(key)
        if (raw) {
          const payload: TurnInput = JSON.parse(raw)
          if (payload.protocol_version === 3 && payload.request_id && typeof payload.question === 'string') {
            recovery.current = payload
            setUnknown(payload)
            const turn = await api.assistantLookup(payload).catch(() => null)
            if (cancelled) return
            if (turn) {
              stored = turn.conversation_id
              // Acceptance is durable: discard question body, keep only the lookup identity.
              saveRecovery(null)
            }
          }
        }
      } catch { setStorageFailed(true) }
      const result = await list()
      if (cancelled) return
      const target = stored || result.recent_id
      if (target) await load(target).catch(async () => {
        if (!cancelled && result.recent_id && result.recent_id !== target) await load(result.recent_id)
      })
    })().catch(cause => { if (!cancelled) setError(cause) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true; alive.current = false; invalidate() }
  }, [key, currentKey, list, load, saveRecovery, invalidate])
  useEffect(() => {
    const logout = () => { alive.current = false; invalidate(); recovery.current = null }
    window.addEventListener('bankpilot-logout', logout)
    return () => window.removeEventListener('bankpilot-logout', logout)
  }, [invalidate])
  const processing = turns.some(turn => turn.status === 'processing')
  useEffect(() => {
    if (!open || !id) return
    let cancelled = false
    const refresh = async () => {
      const version = epoch.current
      try {
        const result = await api.assistantConversation(id)
        if (cancelled || version !== epoch.current) return
        setTurns(old => {
          const replacements = new Map(result.turns.map(turn => [turn.id, turn]))
          return [...old.filter(turn => !replacements.has(turn.id)), ...result.turns]
        })
      } catch (cause) { if (!cancelled) setError(cause) }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, processing ? 3000 : 15000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [open, id, processing])
  async function send(payload: TurnInput) {
    const version = epoch.current
    setError(null)
    saveRecovery(payload)
    try {
      const result = await api.assistantTurn(payload)
      if (!alive.current || epoch.current !== version) return
      saveRecovery(null)
      await load(result.conversation_id)
      await list()
      return true
    } catch (cause) {
      if (!alive.current || epoch.current !== version) return
      // A transport error is not evidence that the server rejected the request.
      const result = await api.assistantLookup(payload).catch(() => null)
      if (!alive.current || epoch.current !== version) return
      if (result) {
        saveRecovery(null)
        await load(result.conversation_id)
        await list()
        return true
      } else {
        if (cause instanceof ApiError && [400, 409, 410, 422].includes(cause.status)) saveRecovery(null)
        setError(cause)
      }
    }
  }
  async function lookup() {
    if (!recovery.current) return
    try {
      const result = await api.assistantLookup(recovery.current)
      if (!alive.current) return
      saveRecovery(null)
      await load(result.conversation_id)
    } catch (cause) { setError(cause) }
  }
  function fresh(inherit = false) {
    epoch.current++
    contextEpoch.current++
    setContextVersion(0); setSearchContext(null); setSearchUnsaved(false)
    active.current = null
    setId(null); setTurns([]); setBefore(null); setError(null); setLoading(false)
    if (!inherit) { setScope(null); setMonth(`${initialMonth.slice(0, 7)}-01`) }
    try { sessionStorage.removeItem(currentKey) } catch { setStorageFailed(true) }
  }
  async function selectScope(value: SpendingScope | null) {
    const target = active.current
    if (target) {
      setLoading(true)
      try { const saved = await api.assistantScope(target, value?.month ?? month, value, contextVersion); if (target === active.current && alive.current) setContextVersion(saved.context_version) }
      finally { if (target === active.current && alive.current) setLoading(false) }
    }
    if (target !== active.current || !alive.current) return
    setScope(value)
    if (value) setMonth(value.month)
  }
  async function selectSearch(filters: SearchFilters | null) {
    const target = active.current
    if (!target) throw new Error('Select a conversation first')
    const version = ++contextEpoch.current
    setSearchUnsaved(true)
    try {
      let saved
      try { saved = await api.assistantSearchContext(target, filters, contextVersion) }
      catch (cause) {
        // A lost success response must be reconciled before retrying a write.
        if (cause instanceof ApiError && cause.status < 500) throw cause
        const current = await api.assistantConversation(target)
        if (current.conversation.context_version !== contextVersion + 1 || JSON.stringify(current.conversation.search_context) !== JSON.stringify(filters)) throw cause
        saved = current.conversation
      }
      if (!alive.current || active.current !== target || contextEpoch.current !== version) return
      setSearchContext(saved.search_context); setContextVersion(saved.context_version); setSearchUnsaved(false)
    } catch (cause) { if (alive.current && active.current === target) setError(cause); throw cause }
  }
  async function remove() {
    if (!id) return
    await api.assistantDelete(id)
    saveRecovery(null)
    fresh()
    await list()
  }
  return { searchContext, contextVersion, searchUnsaved, selectSearch, setSearchUnsaved, items, turns, setTurns, id, scope, month, cursor, before, limit, unknown, storageFailed,
    error, setError, loading, processing, load, list, send, lookup, fresh, selectScope, remove }
}
