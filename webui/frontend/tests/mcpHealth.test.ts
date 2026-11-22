import assert from 'node:assert/strict'
import { test } from 'node:test'
import { api } from '../app/lib/api'
import { getMcpHealthSnapshot, sweepMcpHealth, testMcpHealth } from '../app/lib/mcpHealth'
import type { McpHealth } from '../app/lib/types'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function row(deep: boolean, healthy: boolean | null): McpHealth {
  return { id: 'a', name: 'a', scope: 'global', healthy, error: healthy === false ? 'failed' : null,
    level: deep ? 'connection' : 'command', checked_at: Date.now() / 1000,
    expires_at: Date.now() / 1000 + (healthy === false ? 10 : 60) }
}

test('late sweep preserves a deep result, and configuration changes discard pending results', async () => {
  const oldList = api.listMcpHealth
  const oldCheck = api.checkMcpHealth
  try {
    const sweep = deferred<McpHealth[]>()
    api.listMcpHealth = () => sweep.promise
    api.checkMcpHealth = async () => row(true, false)
    const sweeping = sweepMcpHealth(true)
    assert.equal(sweepMcpHealth(), sweeping, 'concurrent mounts share the request')
    await testMcpHealth('a')
    sweep.resolve([row(false, null)])
    await sweeping
    assert.equal(getMcpHealthSnapshot().rows.a.healthy, false)
    const pending = deferred<McpHealth>()
    api.checkMcpHealth = () => pending.promise
    const testing = testMcpHealth('a')
    api.listMcpHealth = async () => []
    await sweepMcpHealth(true)
    pending.resolve(row(true, true))
    await testing
    assert.deepEqual(getMcpHealthSnapshot().rows, {})

    const stale = deferred<McpHealth[]>()
    api.listMcpHealth = () => stale.promise
    const request = sweepMcpHealth(true)
    api.listMcpHealth = async () => []
    await sweepMcpHealth(true)
    stale.resolve([row(true, true)])
    await request
    assert.deepEqual(getMcpHealthSnapshot().rows, {})
  } finally {
    api.listMcpHealth = oldList
    api.checkMcpHealth = oldCheck
  }
})

test('failed results expire according to their own expiry, not a fresh 60 seconds', async () => {
  const previous = api.listMcpHealth
  let calls = 0
  api.listMcpHealth = async () => { calls++; return [{ ...row(true, false), expires_at: 1 }] }
  try {
    await sweepMcpHealth(true)
    await sweepMcpHealth()
    assert.equal(calls, 2)
  } finally { api.listMcpHealth = previous }
})
