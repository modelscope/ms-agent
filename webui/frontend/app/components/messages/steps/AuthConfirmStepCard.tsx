import { Typography } from 'antd'
import { useEffect, useState } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import { InlineCode } from '../InlineCode'
import AuthorizeIcon from '~/assets/icons/authorize.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

type AuthState = 'pending' | 'approved' | 'rejected' | 'cancelled'

/**
 * Authorization confirm card: renders as a tool-call accordion showing the
 * tool name and parameters, with approve/reject buttons when pending.
 *
 * The `desc` field from the backend is formatted as "tool_name {args_json}".
 * We parse it to show structured UI (same accordion style as ToolCallStepCard).
 */
export function AuthConfirmStepCard({
  step,
  isLast
}: {
  step: AgentStep
  /** Expanded while it's the message's last part; auto-collapses after. */
  isLast?: boolean
}) {
  const { t } = useT()
  const metaState = (step.meta.state as AuthState) ?? 'pending'
  const [localState, setLocalState] = useState<AuthState | null>(null)
  const state = localState ?? metaState
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(
    (isLast ?? false) || metaState === 'pending'
  )

  // Auto-collapse once newer parts arrive — except while pending (buttons
  // must stay visible for the user to decide).
  useEffect(() => {
    if (!isLast && state !== 'pending') setExpanded(false)
  }, [isLast, state])

  const desc = String(step.meta.desc ?? '')
  const requestId = String(step.meta.request_id ?? '')
  const sessionId = String(step.meta.session_id ?? '')

  // Parse "tool_name {args_json}" from desc
  const firstBrace = desc.indexOf('{')
  const toolName = firstBrace > 0 ? desc.slice(0, firstBrace).trim() : desc
  const argsRaw = firstBrace > 0 ? desc.slice(firstBrace) : ''
  let argsFormatted = argsRaw
  try {
    if (argsRaw) argsFormatted = JSON.stringify(JSON.parse(argsRaw), null, 2)
  } catch {
    // Keep raw if not valid JSON
  }

  const resolve = async (action: 'allow_once' | 'allow_always' | 'deny') => {
    const next: AuthState = action === 'deny' ? 'rejected' : 'approved'
    if (!requestId || !sessionId) {
      setState(next)
      return
    }
    setBusy(true)
    try {
      // allow_always: the SDK also records the tool into the project's
      // permission memory (.ms_agent/permission_memory.json), so future calls
      // of the same tool skip the ask entirely.
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

  const setState = (next: AuthState) => {
    setLocalState(next)
    // Also write into the part's meta so the streaming layer can see the
    // decision: agentProvider merges the tool's RESULT step into this card
    // (approved → replace in place; rejected → drop the errored result step).
    step.meta.state = next
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-2">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-none px-3 py-2 text-left transition-colors outline-none cursor-pointer bg-msa-fill-2"
      >
        {/* Its own glyph (check-in-box), not the tool-call wrench: the card asks
            for a decision, so it must not read as "a tool ran". */}
        <AuthorizeIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
        <Typography.Text
          className="min-w-0 flex-1 !text-sm !text-msa-text-1"
          ellipsis={{
            tooltip: `${
              step.meta.source === 'mcp'
                ? t.chat.stepInvokeMcp
                : t.chat.stepInvokeTool
            } ${toolName}`
          }}
        >
          <span className="align-middle">
            {step.meta.source === 'mcp'
              ? t.chat.stepInvokeMcp
              : t.chat.stepInvokeTool}
          </span>{' '}
          <InlineCode>{toolName}</InlineCode>
        </Typography.Text>
        {state === 'rejected' && (
          <span className="shrink-0 text-xs text-msa-text-3">
            {t.chat.authRejected}
          </span>
        )}
        {state === 'cancelled' && (
          <span className="shrink-0 text-xs text-msa-text-3">
            {t.chat.authCancelled}
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
            {argsFormatted && (
              <div>
                <div className="mb-1 text-xs font-medium text-msa-text-3">
                  {t.chat.detailArguments}
                </div>
                <pre className="m-0 max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-msa-fill-1 p-2 font-mono text-xs leading-relaxed text-msa-text-2">
                  {argsFormatted}
                </pre>
              </div>
            )}

            {/* Authorization state: deny / always allow (persisted) / allow once */}
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
