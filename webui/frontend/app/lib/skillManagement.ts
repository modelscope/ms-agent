import { useCallback, useEffect, useRef } from 'react'
import { api, ApiError } from './api'
import type { SkillManagementError, SkillOperation } from './types'
import type en from './locales/en.json'

export class SkillOperationError extends Error {
  constructor(readonly detail: SkillManagementError) {
    super(detail.message)
  }
}

export function skillErrorText(
  error: unknown,
  text: typeof en.skillManagement
): string {
  const code =
    error instanceof SkillOperationError
      ? error.detail.code
      : error instanceof ApiError && error.status === 410
        ? 'PLAN_EXPIRED'
        : ''
  const labels: Record<string, string> = {
    SKILL_BUSY: text.busy,
    PLAN_STALE: text.stale,
    PLAN_EXPIRED: text.expired,
    SOURCE_UNAVAILABLE: text.unavailable,
    SKILL_MOVED_OR_REMOVED: text.notFound,
    AUTH_REQUIRED: text.authorization,
    RATE_LIMITED: text.rateLimited,
    UNSUPPORTED_SOURCE: text.unsupported,
    SKILL_NOT_FOUND: text.notFound,
    PACKAGE_TOO_LARGE: text.tooLarge,
    INVALID_PACKAGE: text.invalid,
    NAME_CONFLICT: text.nameConflict,
    ALREADY_INSTALLED: text.alreadyInstalled,
    SOURCE_CONFLICT: text.sourceConflict,
    LOCAL_MODIFIED: text.overwriteNotice,
    BASELINE_UNKNOWN: text.unknownBaseline,
    SAFETY_REVIEW_REQUIRED: text.safetyReview,
    INTERRUPTED: text.interrupted
  }
  return labels[code] || text.failed
}

function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('Cancelled', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, ms)
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
  })
}

export async function waitSkillOperation<T>(
  initial: SkillOperation<T>,
  signal: AbortSignal,
  onProgress?: (operation: SkillOperation<T>) => void
): Promise<T> {
  let operation = initial
  const deadline = Date.now() + 300_000
  const publish = () => {
    // A cancelled observer must not publish a response already in flight.
    if (signal.aborted) throw new DOMException('Cancelled', 'AbortError')
    onProgress?.(operation)
  }
  publish()
  while (operation.status === 'queued' || operation.status === 'running') {
    await pause(700, signal)
    operation = await api.skillOperation<T>(operation.id)
    if (Date.now() > deadline)
      throw new SkillOperationError({
        code: 'INTERRUPTED',
        message: 'Timed out'
      })
    publish()
  }
  if (signal.aborted) throw new DOMException('Cancelled', 'AbortError')
  if (operation.error) throw new SkillOperationError(operation.error)
  if (operation.status === 'cancelled' || operation.status === 'interrupted') {
    throw new SkillOperationError({
      code: 'INTERRUPTED',
      message: 'Interrupted'
    })
  }
  return operation.result as T
}

/** Polling belongs to the mounted surface; server writes survive navigation. */
export function useSkillOperation() {
  const active = useRef<{
    controller: AbortController
    id?: string
    cancelRequested: boolean
  } | null>(null)
  useEffect(() => () => active.current?.controller.abort(), [])

  const run = useCallback(
    async <T>(
      launch: () => Promise<SkillOperation<T>>,
      onProgress?: (operation: SkillOperation<T>) => void
    ) => {
      active.current?.controller.abort()
      const current = {
        controller: new AbortController(),
        id: undefined as string | undefined,
        cancelRequested: false
      }
      active.current = current
      const operation = await launch()
      current.id = operation.id
      if (current.cancelRequested)
        await api.cancelSkillOperation(operation.id).catch(() => {})
      return waitSkillOperation(operation, current.controller.signal, onProgress)
    },
    []
  )

  const cancel = useCallback(async () => {
    const current = active.current
    if (!current) return
    current.cancelRequested = true
    current.controller.abort()
    if (current.id) await api.cancelSkillOperation(current.id).catch(() => {})
  }, [])
  return { run, cancel }
}

export const isCancelled = (error: unknown) =>
  error instanceof DOMException && error.name === 'AbortError'
