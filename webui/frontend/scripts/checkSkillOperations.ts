import assert from 'node:assert/strict'
import { waitSkillOperation, SkillOperationError } from '../app/lib/skillManagement'
import type { SkillItemResult, SkillOperation } from '../app/lib/types'

// Exercise the real API decoder and polling lifecycle with controlled HTTP
// responses. No timing-dependent UI assertions or production test switches.
const originalFetch = globalThis.fetch
const timeout = setTimeout(() => { throw new Error('Skill operation checks timed out') }, 15_000)
const success: SkillItemResult = { item_id: 'first', status: 'succeeded' }
const failed: SkillItemResult = {
  item_id: 'second', status: 'failed',
  error: { code: 'NAME_CONFLICT', message: 'Already present' }
}
function operation(overrides: Partial<SkillOperation<SkillItemResult[]>> = {}) {
  return {
    id: 'test-operation', kind: 'applying', status: 'queued', result: null,
    error: null, completed: 0, total: null, ...overrides
  } satisfies SkillOperation<SkillItemResult[]>
}
function response(row: SkillOperation<SkillItemResult[]>) {
  return Response.json({ code: 0, message: 'success', data: row })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

try {
  // A first item must become visible while the second is still running. A
  // partial completion keeps both independent results instead of throwing.
  const observed: SkillOperation<SkillItemResult[]>[] = []
  const progress = deferred<void>()
  const finish = deferred<Response>()
  let requests = 0
  let settled = false
  globalThis.fetch = async () => ++requests === 1
    ? response(operation({
        status: 'running', result: [success], completed: 1, total: 2
      }))
    : finish.promise
  const pending = waitSkillOperation(operation(), new AbortController().signal,
    (row) => {
      observed.push(row)
      if (row.completed === 1) progress.resolve()
    }).then((result) => { settled = true; return result })
  await progress.promise
  assert.equal(settled, false)
  assert.equal(observed.at(-1)?.result?.[0].status, 'succeeded')
  finish.resolve(response(operation({
    status: 'partial', result: [success, failed], completed: 2, total: 2
  })))
  assert.deepEqual(await pending, [success, failed])
  assert.deepEqual(observed.map((r) => r.status), ['queued', 'running', 'partial'])
  console.log('PASS progress is published before partial completion')

  // Cancellation during a pending GET must suppress its late progress. This
  // prevents closing and reopening an install modal from receiving old state.
  const entered = deferred<void>()
  const late = deferred<Response>()
  const controller = new AbortController()
  const lateObserved: string[] = []
  globalThis.fetch = async () => { entered.resolve(); return late.promise }
  const cancelled = waitSkillOperation(operation(), controller.signal,
    (row) => { lateObserved.push(row.status) })
  await entered.promise
  controller.abort()
  late.resolve(response(operation({ status: 'succeeded', result: [success] })))
  await assert.rejects(cancelled, { name: 'AbortError' })
  assert.deepEqual(lateObserved, ['queued'])
  console.log('PASS cancelled observers ignore in-flight responses')

  // A response to an already-cancelled launch must not publish or start polling.
  requests = 0
  globalThis.fetch = async () => { requests++; throw new Error('Unexpected GET') }
  const preCancelled = new AbortController()
  preCancelled.abort()
  await assert.rejects(
    waitSkillOperation(operation(), preCancelled.signal, () => assert.fail('Late launch')),
    { name: 'AbortError' }
  )
  assert.equal(requests, 0)
  console.log('PASS cancellation before observation starts')

  // Fast operations can already be complete in the POST response.
  const fastObserved: string[] = []
  const fast = await waitSkillOperation(
    operation({ status: 'succeeded', result: [success], completed: 1, total: 1 }),
    new AbortController().signal, (row) => { fastObserved.push(row.status) }
  )
  assert.deepEqual(fast, [success])
  assert.deepEqual(fastObserved, ['succeeded'])
  assert.equal(requests, 0)
  console.log('PASS immediate completion publishes the final result')

  const aborted = operation({ status: 'cancelled', result: [success] })
  await assert.rejects(
    waitSkillOperation(aborted, new AbortController().signal),
    (error: unknown) => error instanceof SkillOperationError && error.detail.code === 'INTERRUPTED'
  )
  await assert.rejects(
    waitSkillOperation(operation({
      status: 'failed', error: { code: 'PLAN_STALE', message: 'Review again' }
    }), new AbortController().signal),
    (error: unknown) => error instanceof SkillOperationError && error.detail.code === 'PLAN_STALE'
  )
  console.log('PASS cancellation and operation errors remain distinct from item failures')
} finally {
  clearTimeout(timeout)
  globalThis.fetch = originalFetch
}
