import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from './api'
import { applyChunk, assertChatStream, historyToAgentMessages } from './agentProvider'
import type { AgentChunk, AgentInput, AgentMessage, HistoryMessage, MessageSegment } from './agentProvider'
import type { ChatMessageItem } from '~/components/messages/MessageList'

export interface PendingInput {
  input_id: string
  request: AgentInput
  delivery: 'queue' | 'steer'
  revision: number
  state: 'pending' | 'delivered' | 'cancelled'
  held: string | null
  error?: string
}

export interface ConversationState {
  pending: PendingInput[]
  running: boolean
  stopping: boolean
  turn_id: string | null
}

export interface InputReceipt extends ConversationState {
  session_id: string
  project_id: string
  input: PendingInput
}

export interface ConversationEvent extends Partial<ConversationState> {
  type: 'snapshot' | 'state' | 'begin' | 'chunk' | 'failure'
  cursor: string
  history?: HistoryMessage[]
  frames?: AgentChunk[]
  chunk?: AgentChunk
  message?: string
}

export interface ChatState extends ConversationState {
  history: ChatMessageItem[]
  active: ChatMessageItem[]
  origin?: number
  failure?: string
}

export function initialChatState(messages: AgentMessage[] = []): ChatState {
  return {
    history: messages.map((message, i) => ({ id: message.messageId ?? `history-${i}`, message, status: 'success' })),
    active: [], pending: [], running: false, stopping: false, turn_id: null
  }
}

function chunkState(state: ChatState, chunk: AgentChunk): ChatState {
  const meta = chunk.meta ?? {}
  if (chunk.type === 'session') return state
  if (chunk.type === 'turn') {
    const elapsed = Number(meta.elapsed_ms ?? 0)
    const origin = Date.now() - elapsed
    return { ...state, origin, active: state.active.map(item =>
      item.message.role === 'assistant' && item.status !== 'success'
        ? { ...item, message: { ...item.message, turnStartedAt: origin } } : item) }
  }
  if (chunk.type === 'input') {
    const input = meta.message as AgentInput['message']
    const id = String(meta.input_id)
    if (state.active.some(item => item.id === id)) return state
    const content = input.content
    const user: AgentMessage = {
      messageId: id, turnId: String(meta.turn_id), role: 'user',
      content: typeof content === 'string' ? content : content.filter(s => s.type === 'text').map(s => s.text).join('\n'),
      segments: Array.isArray(content) ? content as MessageSegment[] : undefined,
      files: input.files
    }
    const active = state.active.map(item => item.status === 'loading' || item.status === 'updating'
      ? { ...item, status: 'success' } : item)
    active.push({ id, message: user, status: 'success' }, {
      id: String(meta.segment_id), status: 'loading', message: {
        role: 'assistant', content: '', turnId: String(meta.turn_id),
        messageId: String(meta.segment_id), turnStartedAt: state.origin
      }
    })
    return { ...state, active, pending: state.pending.filter(item => item.input_id !== id) }
  }
  const active = [...state.active]
  if (!active.length || active[active.length - 1].message.role !== 'assistant') {
    active.push({ id: `${state.turn_id}-assistant`, status: 'loading',
      message: { role: 'assistant', content: '', turnStartedAt: state.origin } })
  }
  const last = active[active.length - 1]
  active[active.length - 1] = { ...last, message: applyChunk(last.message, chunk),
    status: chunk.type === 'done' ? 'success' : 'updating' }
  return { ...state, active }
}

/** One reducer for live delivery, reconnect replay and full snapshots. */
export function reduceConversation(state: ChatState, event: ConversationEvent): ChatState {
  if (event.type === 'snapshot') {
    const next = { ...initialChatState(historyToAgentMessages(event.history)),
      pending: event.pending ?? [], running: !!event.running,
      stopping: !!event.stopping, turn_id: event.turn_id ?? null }
    return (event.frames ?? []).reduce(chunkState, next)
  }
  if (event.type === 'state') return { ...state,
    pending: event.pending ?? state.pending, running: !!event.running,
    stopping: !!event.stopping, turn_id: event.turn_id ?? null }
  if (event.type === 'begin') return { ...state, active: [], running: true,
    turn_id: event.turn_id ?? null, origin: Date.now(), failure: undefined }
  if (event.type === 'chunk' && event.chunk) return chunkState(state, event.chunk)
  if (event.type === 'failure') return { ...state, failure: event.message }
  return state
}

export function useSessionChat(sessionId: string | null, seed: AgentMessage[] = []) {
  const [state, setState] = useState(() => initialChatState(seed))
  const [generation, setGeneration] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [connectionError, setConnectionError] = useState(false)
  const stateRef = useRef(state)
  stateRef.current = state
  const retry = useRef<{ signature: string; request: AgentInput } | null>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useEffect(() => {
    if (!sessionId) return
    const abort = new AbortController()
    let cursor = ''
    let raf = 0
    let fallback = 0
    let batch: ConversationEvent[] = []
    const flush = () => {
      raf = 0
      clearTimeout(fallback)
      if (!batch.length || abort.signal.aborted) return
      const events = batch
      batch = []
      cursor = events[events.length - 1].cursor
      setState(previous => events.reduce(reduceConversation, previous))
    }
    const consume = async () => {
      while (!abort.signal.aborted) {
        try {
          const response = await assertChatStream(await fetch(`/api/chat/sessions/${sessionId}/events`, {
            signal: abort.signal, headers: cursor ? { 'Last-Event-ID': cursor } : {}
          }))
          setConnectionError(false)
          const reader = response.body!.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          try {
            while (!abort.signal.aborted) {
              const { value, done } = await reader.read()
              if (done) break
              buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
              let split: number
              while ((split = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, split)
                buffer = buffer.slice(split + 2)
                const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
                if (!data) continue
                batch.push(JSON.parse(data) as ConversationEvent)
                if (!raf) {
                  raf = requestAnimationFrame(flush)
                  // Browsers suspend rAF in background tabs. Keep that viewer
                  // current without retaining an entire task's token events.
                  fallback = window.setTimeout(() => { cancelAnimationFrame(raf); flush() }, 100)
                }
              }
            }
          } finally { reader.releaseLock() }
          flush()
        } catch {
          if (abort.signal.aborted) break
          flush()
          setConnectionError(true)
        }
        if (!abort.signal.aborted) await new Promise<void>(resolve => {
          const timer = setTimeout(done, 1500)
          function done() { clearTimeout(timer); abort.signal.removeEventListener('abort', done); resolve() }
          abort.signal.addEventListener('abort', done, { once: true })
        })
      }
    }
    void consume()
    return () => { abort.abort(); cancelAnimationFrame(raf); clearTimeout(fallback) }
  }, [sessionId, generation])

  const submit = useCallback(async (request: AgentInput): Promise<InputReceipt> => {
    const signature = JSON.stringify(request)
    const storageKey = `msa:input:${request.session_id ?? `new:${request.project_id ?? ''}`}`
    if (!retry.current) {
      try { retry.current = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null') }
      catch { /* Storage may be disabled; same-view retries still deduplicate. */ }
    }
    if (retry.current?.signature !== signature) {
      retry.current = { signature, request: { ...request, input_id: crypto.randomUUID(),
        expected_turn_id: stateRef.current.turn_id } }
    }
    const body = retry.current.request
    try { sessionStorage.setItem(storageKey, JSON.stringify(retry.current)) } catch { /* optional */ }
    setSubmitting(true)
    const timer = setTimeout(() => setConfirming(true), 8000)
    try {
      while (alive.current) {
        try {
          const receipt = await api.submitInput(body)
          retry.current = null
          try { sessionStorage.removeItem(storageKey) } catch { /* optional */ }
          return receipt
        } catch (error) {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) {
            retry.current = null
            try { sessionStorage.removeItem(storageKey) } catch { /* optional */ }
            throw error
          }
          setConfirming(true)
          await new Promise(resolve => setTimeout(resolve, 1500))
        }
      }
      throw new Error('View closed')
    } finally {
      clearTimeout(timer)
      if (alive.current) { setConfirming(false); setSubmitting(false) }
    }
  }, [])

  return { state, submit, submitting, confirming, connectionError,
    refresh: useCallback(() => setGeneration(value => value + 1), []) }
}
