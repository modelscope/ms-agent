import { Typography } from 'antd'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import type { OnOpenStep } from '../types'
import { InlineCode } from '../InlineCode'
import { StepInProgressRow, stepHasInProgressRow } from './StepCardShell'
import InvokeIcon from '~/assets/icons/invoke.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

type ToolState = 'pending' | 'approved' | 'rejected' | 'cancelled'

/**
 * Tool-call step card: a collapsible accordion showing tool name, arguments,
 * and result. Supports authorization flow (approve/reject) when the tool
 * requires permission (`meta.state === 'pending'`).
 */
export function ToolCallStepCard({
  step,
  onOpenStep: _onOpenStep,
  isLast,
  icon,
  title,
  titleText
}: {
  step: AgentStep
  onOpenStep?: OnOpenStep
  /** Expanded while it's the message's last part; auto-collapses after. */
  isLast?: boolean
  /** Header icon override (defaults to the generic invoke icon). */
  icon?: ReactNode
  /** Header title override (defaults to the localized "Call {tool name}"). */
  title?: ReactNode
  /** Plain-text mirror of `title` for the overflow tooltip (rich nodes like
   * InlineCode read badly on the dark tooltip background). */
  titleText?: string
}) {
  const { t } = useT()
  const meta = step.meta
  const name = String(meta.tool ?? meta.name ?? '')
  const args = meta.arguments
  const argsStr =
    args && typeof args === 'object'
      ? JSON.stringify(args, null, 2)
      : String(args ?? '')
  const result = String(meta.result ?? '')

  const metaState = (meta.state as ToolState | undefined) ?? null
  const [localState, setLocalState] = useState<ToolState | null>(null)
  const state = localState ?? metaState
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(
    (isLast ?? false) || metaState === 'pending'
  )

  // Auto-collapse once newer parts arrive (mirrors ThoughtsFlow) — except a
  // pending authorization, whose buttons must stay visible.
  useEffect(() => {
    if (!isLast && state !== 'pending') setExpanded(false)
  }, [isLast, state])

  const requestId = String(meta.request_id ?? '')
  const sessionId = String(meta.session_id ?? '')

  // A denied call (live rejection, or history replay where the errored result
  // reads "Tool call denied") shows only the arguments — the denial itself is
  // conveyed by the header badge, not a useless result block.
  const denied =
    state === 'rejected' ||
    (meta.status === 'error' && /denied/i.test(String(meta.error ?? result)))
  // A genuinely failed call (execution error / interruption, not a denial):
  // badge in the header + the error rendered in the danger tone.
  const failed = meta.status === 'error' && !denied
  const errorText = String(meta.error ?? result ?? '')

  const resolve = async (action: 'allow_once' | 'allow_always' | 'deny') => {
    const next: ToolState = action === 'deny' ? 'rejected' : 'approved'
    if (!requestId || !sessionId) {
      setState(next)
      return
    }
    setBusy(true)
    try {
      const { resolved } = await api.resolvePermission({
        session_id: sessionId,
        request_id: requestId,
        action
      })
      setState(resolved ? next : 'rejected')
    } catch {
      // Global error toast handles it.
    } finally {
      setBusy(false)
    }
  }

  const setState = (next: ToolState) => {
    setLocalState(next)
    // Also write the decision into the part's meta: the streaming layer reads it
    // to decide what to do with the tool's RESULT step (rejected → the errored
    // result is dropped so this card keeps telling the "rejected" story). Mirrors
    // AuthConfirmStepCard — required now that asks are hosted by this card
    // (backend _AUTH_INLINE_KINDS), where a missed write-back made a REFUSED call
    // end up rendered as "call failed".
    step.meta.state = next
  }

  // In progress — either of the two ways a call can be mid-flight:
  // - status "running": announced by tool_call_started, result frame not in yet;
  // - approved here with the ask still on the card and no result.
  // Rendered in the HEADER (spinner in place of the tool glyph), so resolving
  // the ask doesn't reflow the card the way a footer row would. This is also the
  // in-progress state for the kinds StepCard routes through this card (browser,
  // file grep/glob, memory, skill_load).
  const executing =
    meta.status === 'running' || (state === 'approved' && !!requestId && !result)

  // A kind with its own in-progress ROW (a web search, a file operation) is only
  // using this accordion for its ASK (details + decision buttons). The moment
  // it's approved it hands back to that row — rendered from here, not from the
  // kind dispatcher, because the approval lives in this component's state and the
  // parent won't re-render until the next stream frame (which can be a minute
  // away for a slow call).
  if (executing && stepHasInProgressRow(step)) {
    return <StepInProgressRow step={step} />
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-none px-3 py-2 text-left transition-colors outline-none cursor-pointer bg-msa-fill-1"
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
          {executing ? (
            <SpinnerIcon
              aria-hidden
              className="h-4 w-4 animate-spin text-msa-text-brand1"
            />
          ) : (
            (icon ?? <InvokeIcon className="h-4 w-4" />)
          )}
        </span>
        <Typography.Text
          className="min-w-0 flex-1 !text-sm !text-msa-text-1"
          ellipsis={{
            tooltip:
              titleText ??
              `${
                meta.source === 'mcp'
                  ? t.chat.stepInvokeMcp
                  : t.chat.stepInvokeTool
              } ${name}`
          }}
        >
          {title ?? (
            <>
              {/* Server-stamped source: MCP servers read "call MCP", built-in
                  (and unknown) ones read "call tool". */}
              <span className="align-middle">
                {meta.source === 'mcp'
                  ? t.chat.stepInvokeMcp
                  : t.chat.stepInvokeTool}
              </span>{' '}
              <InlineCode>{name}</InlineCode>
            </>
          )}
        </Typography.Text>
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

      {/* Body: animated accordion */}
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-in-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-msa-line-1 px-3 py-2 space-y-2">
            {/* Arguments */}
            {argsStr && (
              <div>
                <div className="mb-1 text-xs font-medium text-msa-text-3">
                  {t.chat.detailArguments}
                </div>
                <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-0 p-2 font-mono text-xs leading-relaxed text-msa-text-2">
                  {argsStr}
                </pre>
              </div>
            )}

            {/* Result: success → normal tone; failure → error tone with the
                error text; denied → hidden entirely. */}
            {failed ? (
              <div>
                <div className="mb-1 text-xs font-medium text-msa-text-danger">
                  {t.chat.detailError}
                </div>
                <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-error p-2 font-mono text-xs leading-relaxed text-msa-text-danger">
                  {errorText}
                </pre>
              </div>
            ) : (
              result &&
              state !== 'pending' &&
              !denied && (
                <div>
                  <div className="mb-1 text-xs font-medium text-msa-text-3">
                    {t.chat.detailResult}
                  </div>
                  <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-0 p-2 font-mono text-xs leading-relaxed text-msa-text-2">
                    {result}
                  </pre>
                </div>
              )
            )}

            {/* Authorization: pending → deny / always run / run once */}
            {state === 'pending' && (
              <div className="flex justify-end gap-2 pt-1">
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
