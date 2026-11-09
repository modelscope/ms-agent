/**
 * Replays recorded frame sequences through the REAL reducer and asserts what the
 * "thinking Ns" header shows. Sequences, not unit calls: what broke here was the
 * reducer's behaviour over a whole stream — a replayed turn (every page refresh)
 * disagreeing with the live pass. Run with `pnpm check:frames`.
 *
 * Per scenario: nothing left ticking, the seconds are the SERVER's, and the
 * replay matches the live pass.
 */
import assert from 'node:assert/strict'
import {
  applyChunk,
  finalizeOpenThoughts,
  historyToAgentMessages,
  type AgentChunk,
  type AgentMessage
} from '~/lib/agentProvider'
import { splitTurn } from '~/components/messages/turnSplit'

type Scenario = {
  name: string
  frames: AgentChunk[]
  /** Expected header per thought block: a number of seconds, `'ticking'` for a
   * block the model has genuinely not finished, `null` for "done, no time". */
  expect: (number | 'ticking' | null)[]
  /** Applied after the frames, mirroring transformMessage's `done` branch. */
  finalize?: boolean
}

const thought = (block: number, text: string, elapsedMs?: number): AgentChunk => ({
  type: 'thought',
  content: text,
  meta: elapsedMs == null ? { block } : { block, elapsed_ms: elapsedMs }
})
const close = (block: number, duration: number): AgentChunk => ({
  type: 'thought',
  content: '',
  meta: { block, duration, elapsed_ms: duration * 1000 }
})
/** A pre-block-id backend: thought frames with no `meta.block` at all. */
const legacyThought = (text: string, duration?: number): AgentChunk => ({
  type: 'thought',
  content: text,
  meta: duration == null ? {} : { duration }
})
const composing = (): AgentChunk => ({
  type: 'step',
  content: '',
  meta: { kind: 'tool_composing', status: 'composing', tool: 'write_file', index: 0 }
})
const step = (kind: string, extra: Record<string, unknown> = {}): AgentChunk => ({
  type: 'step',
  content: '',
  meta: { kind, call_id: 'c1', group: 1, ...extra }
})
const text = (s: string): AgentChunk => ({ type: 'text', content: s, meta: {} })
const task = (id: string, label: string): AgentChunk => ({
  type: 'task',
  content: '',
  meta: { id, label, status: 'running' }
})
const error = (message: string): AgentChunk => ({
  type: 'error',
  content: '',
  meta: { message, recoverable: false }
})
const compaction = (): AgentChunk => ({
  type: 'step',
  content: '',
  meta: { kind: 'context_compaction', before_tokens: 12000, after_tokens: 4000 }
})

const SCENARIOS: Scenario[] = [
  {
    name: 'context compaction does not finish in-flight reasoning',
    frames: [thought(1, 'still thinking', 0), compaction()],
    expect: ['ticking']
  },
  {
    name: 'context compaction preserves reasoning identity and server duration',
    frames: [
      thought(1, 'before', 0), compaction(), thought(1, ' after', 2000), close(1, 4)
    ],
    expect: [4]
  },
  {
    // The common shape: think, then a tool call with no narration.
    name: 'think → tool call (no narration)',
    frames: [
      thought(1, '先想清楚要写什么', 0),
      thought(1, '，分五段。', 9000),
      close(1, 10),
      composing(),
      step('file_write', { status: 'running', path: 'a.md' }),
      step('file_write', { path: 'a.md' })
    ],
    expect: [10]
  },
  {
    // A round that narrates first: the close lands before the text.
    name: 'think → narration → tool call',
    frames: [
      thought(1, '先看目录', 0),
      close(1, 3),
      text('我先看一下当前目录。'),
      composing(),
      step('file_write', { status: 'running', path: 'b.md' })
    ],
    expect: [3]
  },
  {
    // A backend that does not seal the block itself: the close lands late, but
    // it names its block, so it still corrects the header.
    name: 'close arrives after the tool-call frames',
    frames: [
      thought(1, '直接开写', 0),
      composing(),
      step('file_write', { status: 'running', path: 'd.md' }),
      close(1, 57),
      step('file_write', { path: 'd.md' })
    ],
    expect: [57]
  },
  {
    // An "always ask" project waits indefinitely, so a wrong number would sit
    // on screen for as long as the user takes to answer.
    name: 'two rounds, second parked on an authorization card',
    frames: [
      thought(1, '想第一步', 0),
      close(1, 12),
      composing(),
      step('search', { status: 'running' }),
      step('search'),
      thought(2, '想第二步', 0),
      close(2, 7),
      composing(),
      step('file_write', { status: 'running', path: 'c.md' }),
      step('file_write', { state: 'pending', request_id: 'r1', path: 'c.md' })
    ],
    expect: [12, 7]
  },
  {
    // Lands mid-reasoning and draws no card: must not cut the block in two.
    name: 'image delivery mid-reasoning does not split the block',
    frames: [
      thought(1, '看看这张图', 0),
      step('image_delivery', { state: 'delivered', index: 0, path: 'user_files/a.png' }),
      thought(1, '，是一张地铁站台照片。', 2000),
      close(1, 4),
      text('图里是站台层。')
    ],
    expect: [4]
  },
  {
    // Todo tools draw no step card, so the plan snapshot is what follows.
    name: 'think → plan snapshot',
    frames: [
      thought(1, '拆成三步', 0),
      close(1, 6),
      composing(),
      task('0', '写第一篇'),
      task('1', '写第二篇')
    ],
    expect: [6]
  },
  {
    // No close will ever come, so the error frame stops the counter — the one
    // case where a client-derived number is allowed.
    name: 'turn errors mid-thought',
    frames: [thought(1, '想到一半', 0), error('RateLimitError: 429')],
    expect: [0]
  },
  {
    // Genuinely still thinking: the block stays open.
    name: 'still thinking (no close yet)',
    frames: [thought(1, '正在想', 0), thought(1, '……', 3000)],
    expect: ['ticking']
  },
  {
    // Same, but the turn's terminal frame arrives: the counter must stop.
    name: 'still thinking, then the turn ends',
    frames: [thought(1, '正在想', 0), thought(1, '……', 3000)],
    expect: [3],
    finalize: true
  },
  {
    // No block ids at all: fold into the tail block, exactly as before.
    name: 'legacy frames without block ids',
    frames: [
      legacyThought('老协议'),
      legacyThought('，没有 block。'),
      legacyThought('', 9),
      text('写完了。')
    ],
    expect: [9]
  },
  {
    // Frontend ahead of the backend: no ids AND a late close — the client's
    // guess must still be corrected. This is what the fix is worth on its own.
    name: 'legacy frames, close after the tool-call frames',
    frames: [
      legacyThought('直接开写'),
      composing(),
      step('file_write', { status: 'running', path: 'f.md' }),
      legacyThought('', 57),
      step('file_write', { path: 'f.md' })
    ],
    expect: [57]
  },
  {
    // No reasoning at all: nothing to show, nothing to break.
    name: 'no reasoning at all',
    frames: [text('好的。'), composing(), step('file_write', { path: 'e.md' })],
    expect: []
  }
]

const headers = (msg: AgentMessage): (number | 'ticking' | null)[] =>
  (msg.parts ?? [])
    .filter((p) => p.kind === 'thought')
    .map((p) =>
      p.kind !== 'thought'
        ? null
        : p.done === false
          ? ('ticking' as const)
          : (p.duration ?? null)
    )

/** Blocks still showing a number this client made up although the server sent
 * one for that block. */
const staleDerived = (msg: AgentMessage, frames: AgentChunk[]): boolean => {
  const served = new Set(
    frames
      .filter((f) => f.type === 'thought' && f.meta?.duration != null)
      .map((f) => f.meta?.block)
  )
  return (msg.parts ?? []).some(
    (p) => p.kind === 'thought' && p.derived === true && served.has(p.block)
  )
}

const reduce = (frames: AgentChunk[], finalize = false): AgentMessage => {
  let msg: AgentMessage = { role: 'assistant', content: '' }
  for (const f of frames) msg = applyChunk(msg, f)
  if (finalize && msg.parts?.some((p) => p.kind === 'thought' && !p.done)) {
    const parts = [...msg.parts]
    finalizeOpenThoughts(parts)
    msg = { ...msg, parts }
  }
  return msg
}

let failed = 0
const fail = (name: string, why: string) => {
  failed++
  console.error(`  ✗ ${name}: ${why}`)
}

for (const s of SCENARIOS) {
  // Same frames, same reducer: only WHEN they arrive differs in the product,
  // which is why the numbers have to come from the server.
  const live = reduce(s.frames, s.finalize)
  const replay = reduce(s.frames, s.finalize)
  const got = headers(live)
  const want = JSON.stringify(s.expect)

  if (JSON.stringify(got) !== want)
    fail(s.name, `expected ${want}, got ${JSON.stringify(got)}`)
  else if (staleDerived(live, s.frames))
    fail(s.name, 'a block kept a client-derived duration although the server sent one')
  else if (JSON.stringify(headers(replay)) !== JSON.stringify(got))
    fail(s.name, 'replay disagrees with the live pass')
  else console.log(`  ✓ ${s.name} → ${JSON.stringify(got)}`)
}

// Compaction is not a tool result or a turn boundary. Exercise the same reducer
// used for live SSE and attach, plus persisted-history conversion, without a DOM.
const beforeNotice = reduce([text('narration'), composing()])
const withNotice = applyChunk(beforeNotice, compaction())
assert.equal(withNotice.content, beforeNotice.content)
assert.equal(withNotice.turnStartedAt, beforeNotice.turnStartedAt)
assert.equal(withNotice.loopDurationMs, undefined)
assert.deepEqual(withNotice.parts?.slice(0, -1), beforeNotice.parts)
assert.equal(splitTurn(withNotice.parts ?? [], true).loopDone, false)

const runningTool = step('file_read', { status: 'running', path: 'a.txt' })
const toolsAndNotice = reduce([runningTool, compaction(), step('file_read', { path: 'a.txt' })])
assert.equal(toolsAndNotice.parts?.length, 2) // completion replaces only the tool
assert.deepEqual(toolsAndNotice.parts?.[0], {
  kind: 'step', step: { kind: 'file_read', meta: { kind: 'file_read', call_id: 'c1', group: 1, path: 'a.txt' } }
})
assert.deepEqual(toolsAndNotice.parts?.[1], {
  kind: 'step', step: { kind: 'context_compaction', meta: compaction().meta }
})

const [history] = historyToAgentMessages([{
  role: 'assistant', content: 'answer', parts: [
    { kind: 'step', step: { kind: 'context_compaction', meta: { before_tokens: 12000, after_tokens: 4000 } } },
    { kind: 'text', text: 'answer' }
  ]
}])
const historyNotice = history.parts?.[0]
assert.equal(history.content, 'answer')
assert.equal(historyNotice?.kind, 'step')
if (historyNotice?.kind === 'step') {
  assert.equal(historyNotice.step.kind, 'context_compaction')
  assert.deepEqual(historyNotice.step.meta, { before_tokens: 12000, after_tokens: 4000 })
}
assert.equal(splitTurn(history.parts ?? [], false).summary?.text, 'answer')
const afterAnswer = reduce([text('answer'), compaction(), compaction()])
const completed = splitTurn(afterAnswer.parts ?? [], false)
assert.equal(completed.summary?.text, 'answer')
assert.deepEqual(completed.processParts, [])
assert.equal(completed.trailingNotices.length, 2)
const streaming = splitTurn(afterAnswer.parts ?? [], true)
assert.equal(streaming.summary, null)
assert.deepEqual(streaming.processParts, afterAnswer.parts)
assert.deepEqual(streaming.trailingNotices, [])
const interrupted = splitTurn([...(afterAnswer.parts ?? []), { kind: 'interrupted' }], false)
assert.equal(interrupted.loopDone, false)
assert.equal(interrupted.summary, null)
console.log('Context compaction reducer, history and turn-boundary checks passed')

if (failed) {
  console.error(`\n${failed} scenario(s) failed`)
  process.exit(1)
}
console.log(`\n${SCENARIOS.length} scenarios ok`)
