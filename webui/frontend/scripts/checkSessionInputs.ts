/** Replay real session event shapes through the UI's single reducer. */
import assert from 'node:assert/strict'
import { initialChatState, reduceConversation, type ConversationEvent, type PendingInput } from '~/lib/sessionChat'
import type { AgentChunk } from '~/lib/agentProvider'

const input = (id: string): PendingInput => ({ input_id: id,
  request: { message: { role: 'user', content: id } }, delivery: 'steer',
  state: 'pending', held: null, revision: 1 })
const chunk = (value: AgentChunk): ConversationEvent => ({ type: 'chunk', chunk: value, cursor: 'epoch:1' })
const delivered = (id: string): AgentChunk => ({ type: 'input', content: '', meta: {
  input_id: id, turn_id: 'task', segment_id: `assistant-${id}`,
  message: { role: 'user', content: id, files: [{ name: 'note.txt', path: 'note.txt' }] }
} })
const frames: AgentChunk[] = [
  delivered('initial'), { type: 'text', content: 'before', meta: {} },
  delivered('steer1'), delivered('steer2'), { type: 'text', content: 'after', meta: {} }
]
let live = reduceConversation(initialChatState(), { type: 'begin', turn_id: 'task', cursor: 'epoch:0' })
live.pending = [input('steer1'), input('steer2'), { ...input('queue'), delivery: 'queue' }]
for (const frame of frames) live = reduceConversation(live, chunk(frame))
assert.deepEqual(live.active.filter(i => i.message.role === 'user').map(i => i.message.content), ['initial', 'steer1', 'steer2'])
assert.deepEqual(live.pending.map(i => i.input_id), ['queue'])
assert.equal(live.active[1].message.content, 'before')
assert.equal(live.active.at(-1)?.message.content, 'after')
const before = live.active.length
live = reduceConversation(live, chunk(delivered('steer2')))
assert.equal(live.active.length, before, 'duplicate delivery must not add bubbles')

const replay = reduceConversation(initialChatState(), { type: 'snapshot', cursor: 'epoch:20',
  history: [], frames, pending: live.pending, running: true, stopping: false, turn_id: 'task' })
assert.deepEqual(replay.active.map(i => ({ ...i.message, turnStartedAt: undefined })),
  live.active.map(i => ({ ...i.message, turnStartedAt: undefined })))
const timed = reduceConversation(replay, chunk({ type: 'turn', content: '', meta: { elapsed_ms: 12000 } }))
assert.ok(Math.abs(Date.now() - timed.active.at(-1)!.message.turnStartedAt! - 12000) < 100)
assert.equal(timed.active[0].message.files?.[0].name, 'note.txt')

const complete = reduceConversation(timed, { type: 'snapshot', cursor: 'epoch:30',
  history: [{ role: 'user', content: 'steer2', message_id: 'steer2', turn_id: 'task' },
    { role: 'assistant', content: 'after', message_id: 'assistant-steer2', turn_id: 'task' }],
  frames: [], pending: [], running: false, stopping: false, turn_id: null })
assert.equal(complete.active.length, 0)
assert.equal(complete.history.length, 2)
assert.equal(complete.history[0].id, 'steer2')
assert.equal(complete.running, false)
console.log('Session inputs: ordering, segmentation, deduplication, replay, timer and completion passed.')
