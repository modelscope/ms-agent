import { useEffect, useState } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import type { OnOpenStep } from '../types'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

type TerminalState = 'pending' | 'approved' | 'rejected' | 'cancelled'

/**
 * Terminal step card: a collapsible accordion showing a shell command.
 *
 * When the command requires authorization (`meta.state === 'pending'`), shows
 * Reject/Run buttons. Once resolved (or for normal unrestricted commands), the
 * code is just displayed in a scrollable area with max height.
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

  const resolve = async (approve: boolean) => {
    const next: TerminalState = approve ? 'approved' : 'rejected'
    if (!requestId || !sessionId) {
      setLocalState(next)
      return
    }
    setBusy(true)
    try {
      const { resolved } = await api.resolvePermission({
        session_id: sessionId,
        request_id: requestId,
        action: approve ? 'allow_once' : 'deny'
      })
      setLocalState(resolved ? next : 'rejected')
    } catch {
      // Global api error toast already fired; keep actionable.
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-2">
      {/* Header: accordion toggle */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-none px-3 py-2 text-left transition-colors outline-none cursor-pointer bg-msa-fill-2"
      >
        <TerminalIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
        <span className="min-w-0 flex-1 truncate text-sm text-msa-text-1">
          {t.chat.stepTerminal}
        </span>
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

            {/* Authorization: pending → buttons, rejected → label */}
            {state === 'pending' && (
              <div className="flex justify-end gap-2 border-t border-msa-line-1 px-3 py-2">
                <MsaButton
                  variant="outlined"
                  disabled={busy}
                  onClick={() => resolve(false)}
                >
                  {t.chat.authReject}
                </MsaButton>
                <MsaButton
                  variant="primary"
                  disabled={busy}
                  onClick={() => resolve(true)}
                >
                  {t.chat.authApprove}
                </MsaButton>
              </div>
            )}
            {state === 'rejected' && (
              <div className="flex justify-end px-3 py-2 text-xs text-msa-text-3">
                {t.chat.authRejected}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
