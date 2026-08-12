import { Typography } from 'antd'
import type { ReactNode } from 'react'
import { FileTypeIcon } from '~/components/common/FileCard'
import { useT } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import { InlineCode } from '../InlineCode'
import JumpIcon from '~/assets/icons/jump.svg?react'
import SearchIcon from '~/assets/icons/search.svg?react'

/**
 * Shared shell for single-line step cards: leading icon + title + trailing
 * jump chevron. Clicking opens the workspace rail via `onClick`. When
 * `disabled` (e.g. a file whose workspace entry was deleted) it renders as a
 * non-interactive card — no chevron, `cursor-not-allowed`, muted title — with
 * an optional trailing `note` (e.g. "this file was deleted").
 *
 * `nonInteractive` is the milder version of that: nothing to open YET (a search
 * still running has no results), so the row keeps its normal look but drops the
 * chevron and the hover/click affordance.
 *
 * Lives in its own module because both the kind dispatcher (StepCard) and
 * ToolCallStepCard render one-line rows — the latter for a web search it is
 * hosting while it executes.
 */
export function StepCardShell({
  icon,
  children,
  onClick,
  disabled = false,
  nonInteractive = false,
  note,
  noteTone = 'danger',
  maxWidthClass = 'max-w-full',
  tipText
}: {
  icon: ReactNode
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  /** Not openable (yet), but not a dead card either — normal tone, no chevron. */
  nonInteractive?: boolean
  note?: ReactNode
  /** A refusal is not an error: it reads in the muted tone, like the badge the
   * accordion cards use, so only genuine failures are red. */
  noteTone?: 'danger' | 'muted'
  maxWidthClass?: string
  /** PLAIN-TEXT tooltip for the clipped label. Required because `children`
   * carries card chrome (InlineCode chips, favicons) styled for the light card
   * surface — rendering that JSX inside antd's dark tooltip produced a pale
   * chip on a dark bubble (unreadable). Mirrors ToolCallStepCard's
   * `titleText`. */
  tipText?: string
}) {
  const noteClass =
    noteTone === 'muted' ? 'text-msa-text-3' : 'text-msa-text-danger'
  if (disabled || nonInteractive) {
    return (
      <div
        className={`flex w-fit items-center gap-2 rounded-xl border border-msa-line-1 bg-msa-fill-1 px-3 py-2 text-left ${
          disabled ? 'cursor-not-allowed' : ''
        } ${maxWidthClass}`}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
          {icon}
        </span>
        <Typography.Text
          ellipsis={{ tooltip: tipText ? { title: tipText } : true }}
          className={`min-w-0 flex-1 !text-sm ${
            disabled ? '!text-msa-text-3' : '!text-msa-text-1'
          }`}
        >
          {children}
        </Typography.Text>
        {note && (
          <span className={`shrink-0 text-xs ${noteClass}`}>{note}</span>
        )}
      </div>
    )
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex w-fit cursor-pointer items-center gap-2 rounded-xl border border-msa-line-1 bg-msa-fill-1 px-3 py-2 text-left transition-colors hover:bg-msa-fill-4 ${maxWidthClass}`}
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
        {icon}
      </span>
      <Typography.Text
        ellipsis={{ tooltip: tipText ? { title: tipText } : true }}
        className="min-w-0 flex-1 !text-sm !text-msa-text-1"
      >
        {children}
      </Typography.Text>
      {/* An openable card can still carry an outcome note (a failed search keeps
          its row clickable so the rail can show the error). */}
      {note && (
        <span className={`shrink-0 text-xs ${noteClass}`}>{note}</span>
      )}
      <JumpIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
    </button>
  )
}

/** The one-line "doing it now" row: an action that is running (or was just
 * approved and is now running). Deliberately NOT openable — there is nothing
 * behind it yet. */
export function InProgressRow({
  label,
  detail,
  icon
}: {
  label: string
  detail: string
  icon: ReactNode
}) {
  return (
    <StepCardShell
      nonInteractive
      icon={icon}
      tipText={detail ? `${label} ${detail}` : label}
    >
      <span className="align-middle">{label}</span>
      {detail ? (
        <>
          {' '}
          <InlineCode>{detail}</InlineCode>
        </>
      ) : null}
    </StepCardShell>
  )
}

/** Whether this step kind has an in-progress ROW of its own (below) rather than
 * showing progress on its accordion card. Both the kind dispatcher and
 * ToolCallStepCard need to know — the latter hosts these kinds' authorization
 * asks and must hand back to the row the moment one is approved. */
export function stepHasInProgressRow(step: AgentStep): boolean {
  switch (step.kind) {
    case 'search':
      return String(step.meta.scope ?? '') !== 'files'
    case 'file_read':
    case 'file_write':
    case 'file_edit':
      return true
    default:
      return false
  }
}

/** In-progress row for the kinds that have one, keeping each action's own
 * identity: a search states its query behind the magnifier, a file operation
 * states its path behind that file type's glyph — the same glyph its finished
 * row uses, so one call keeps one look from ask to result. */
export function StepInProgressRow({ step }: { step: AgentStep }) {
  const { t } = useT()
  const meta = step.meta
  const path = String(meta.path ?? '')
  const fileIcon = <FileTypeIcon name={path} className="h-4 w-4" />
  switch (step.kind) {
    case 'search':
      return (
        <InProgressRow
          label={t.chat.stepSearching}
          detail={String(meta.query ?? '')}
          icon={<SearchIcon className="h-4 w-4" />}
        />
      )
    case 'file_read':
      return (
        <InProgressRow
          label={t.chat.stepFileReading}
          detail={path}
          icon={fileIcon}
        />
      )
    case 'file_write':
      return (
        <InProgressRow
          label={t.chat.stepFileWriting}
          detail={path}
          icon={fileIcon}
        />
      )
    case 'file_edit':
      return (
        <InProgressRow
          label={t.chat.stepFileEditing}
          detail={path}
          icon={fileIcon}
        />
      )
    default:
      return null
  }
}
