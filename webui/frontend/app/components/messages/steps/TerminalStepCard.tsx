import { useEffect, useState } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import type { OnOpenStep } from '../types'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

type TerminalState = 'pending' | 'approved' | 'rejected' | 'cancelled'

/** The code executor answers with a JSON envelope
 * (`{success, output, error, return_code, truncated}`), not raw stdout. Unpack it
 * so the card can show the OUTPUT the way a terminal does — and so a non-zero
 * exit reads as a failure, which the tool call's own status never reports (the
 * CALL succeeded; the command inside it didn't).
 *
 * Anything that isn't that envelope (an interrupt marker, a plain-text result
 * from another executor) is passed through as the output verbatim.
 */
function parseExecResult(raw: string): {
  output: string
  error: string
  exitFailed: boolean
} {
  if (!raw) return { output: '', error: '', exitFailed: false }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const env = parsed as Record<string, unknown>
      if ('output' in env || 'return_code' in env) {
        const code = env.return_code
        return {
          output: String(env.output ?? ''),
          error: String(env.error ?? ''),
          exitFailed:
            env.success === false ||
            (typeof code === 'number' && code !== 0)
        }
      }
    }
  } catch {
    // Not JSON: a plain-text result. Fall through.
  }
  return { output: raw, error: '', exitFailed: false }
}

/**
 * Terminal step card: a collapsible accordion showing a shell command.
 *
 * When the command requires authorization (`meta.state === 'pending'`), shows
 * the same three-way decision as the generic authorization card (reject / always
 * run / run once) — a shell ask is rendered by THIS card, because the command is
 * what the user is judging. Once resolved (or for normal unrestricted commands),
 * the code is just displayed in a scrollable area with max height.
 */
export function TerminalStepCard({
  step,
  onOpenStep: _onOpenStep,
  isLast
}: {
  step: AgentStep
  onOpenStep?: OnOpenStep
  /** Expanded while it's the message's last part; auto-collapses after. */
  isLast?: boolean
}) {
  const { t } = useT()
  const code = String(step.meta.code ?? '')
  const metaState = (step.meta.state as TerminalState | undefined) ?? null
  const [localState, setLocalState] = useState<TerminalState | null>(null)
  const state = localState ?? metaState
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(
    (isLast ?? false) || metaState === 'pending'
  )

  // Auto-collapse once newer parts arrive — except a pending authorization.
  useEffect(() => {
    if (!isLast && state !== 'pending') setExpanded(false)
  }, [isLast, state])

  const requestId = String(step.meta.request_id ?? '')
  const sessionId = String(step.meta.session_id ?? '')

  // In progress — either of the two ways a command can be mid-flight:
  // - status "running": the SDK announced the call (tool_call_started) and its
  //   result frame hasn't replaced this card yet;
  // - approved here (or re-attached as approved) with the ask still on the card.
  // Rendered in the HEADER (spinner in place of the terminal glyph), so
  // resolving the ask doesn't reflow the card the way a footer row would.
  const executing =
    step.meta.status === 'running' || (state === 'approved' && !!requestId)

  // Outcome badges live in the HEADER next to the title (same slot as
  // "executing"), so a collapsed card still states how the command ended and
  // the body stays purely the command itself. Mirrors ToolCallStepCard:
  // - denied: refused here, or replayed from history where the sealed result
  //   reads "Tool call denied";
  // - failed: a real execution error / interruption, not a refusal.
  const errorText = String(step.meta.error ?? '')
  const rawResult = String(step.meta.result ?? '')
  const exec = parseExecResult(rawResult)
  const denied =
    state === 'rejected' ||
    (step.meta.status === 'error' &&
      /denied/i.test(String(step.meta.error ?? rawResult)))
  // A failed run is either a failed CALL (execution error / interruption) or a
  // command that exited non-zero.
  const failed = (step.meta.status === 'error' || exec.exitFailed) && !denied
  const failureText = errorText || exec.error || exec.output || rawResult
  // Output gets its own block whenever there is any — except when the error
  // block below would print that very same text (an interrupted call stores the
  // same marker in both `result` and `error`). The guard only applies when that
  // error block actually renders, since `failureText` falls back to the output.
  const showOutput =
    !!exec.output &&
    state !== 'pending' &&
    !denied &&
    (!failed || exec.output !== failureText)

  const resolve = async (action: 'allow_once' | 'allow_always' | 'deny') => {
    const next: TerminalState = action === 'deny' ? 'rejected' : 'approved'
    if (!requestId || !sessionId) {
      setState(next)
      return
    }
    setBusy(true)
    try {
      // allow_always also records the tool in the project's permission memory
      // (SDK side), so later commands skip the ask entirely.
      const { resolved } = await api.resolvePermission({
        session_id: sessionId,
        request_id: requestId,
        action
      })
      setState(resolved ? next : 'rejected')
    } catch {
      // Global api error toast already fired; keep actionable.
    } finally {
      setBusy(false)
    }
  }

  const setState = (next: TerminalState) => {
    setLocalState(next)
    // Write the decision into the part's meta too — the streaming layer drops a
    // REFUSED call's errored result step by reading it, so this card keeps
    // telling the "rejected" story instead of flipping to "call failed".
    step.meta.state = next
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1">
      {/* Header: accordion toggle */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-none px-3 py-2 text-left transition-colors outline-none cursor-pointer bg-msa-fill-1"
      >
        {executing ? (
          <SpinnerIcon
            aria-hidden
            className="h-4 w-4 shrink-0 animate-spin text-msa-text-brand1"
          />
        ) : (
          <TerminalIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm text-msa-text-1">
          {t.chat.stepTerminal}
        </span>
        {executing && (
          <span className="shrink-0 text-xs text-msa-text-3">
            {t.chat.authExecuting}
          </span>
        )}
        {denied && (
          <span className="shrink-0 text-xs text-msa-text-3">
            {t.chat.authRejected}
          </span>
        )}
        {failed && (
          <span className="shrink-0 text-xs text-msa-text-danger">
            {t.chat.callFailed}
          </span>
        )}
        <ArrowDownIcon
          className={`h-3 w-3 shrink-0 text-msa-text-3 transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Body: animated accordion via grid-template-rows transition */}
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-in-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-msa-line-1">
            <div className="max-h-[200px] overflow-y-auto px-3 py-2">
              <pre className="m-0 whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-msa-text-2">
                {code}
              </pre>
            </div>

            {/* Command output — the executor's `output`, not its JSON envelope. */}
            {showOutput && (
              <div className="border-t border-msa-line-1 px-3 py-2">
                <div className="mb-1 text-xs font-medium text-msa-text-3">
                  {t.chat.detailResult}
                </div>
                <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-0 p-2 font-mono text-xs leading-relaxed text-msa-text-2">
                  {exec.output}
                </pre>
              </div>
            )}

            {/* Failure detail: stderr / execution error / interruption marker.
                Shown in addition to the output above (a command can print and
                then still fail) — unlike a pure tool call, where the two are
                mutually exclusive. */}
            {failed && !!failureText && (
              <div className="border-t border-msa-line-1 px-3 py-2">
                <div className="mb-1 text-xs font-medium text-msa-text-danger">
                  {t.chat.detailError}
                </div>
                <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-error p-2 font-mono text-xs leading-relaxed text-msa-text-danger">
                  {failureText}
                </pre>
              </div>
            )}

            {/* Authorization: pending → deny / always run / run once */}
            {state === 'pending' && (
              <div className="flex justify-end gap-2 border-t border-msa-line-1 px-3 py-2">
                <MsaButton
                  variant="outlined"
                  disabled={busy}
                  onClick={() => resolve('deny')}
                >
                  {t.chat.authReject}
                </MsaButton>
                <MsaButton
                  variant="outlined"
                  disabled={busy}
                  onClick={() => resolve('allow_always')}
                >
                  {t.chat.authApproveAlways}
                </MsaButton>
                <MsaButton
                  variant="primary"
                  disabled={busy}
                  onClick={() => resolve('allow_once')}
                >
                  {t.chat.authApprove}
                </MsaButton>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
