import { Typography } from 'antd'
import type { ReactNode } from 'react'
import { FileTypeIcon } from '~/components/common/FileCard'
import { useT } from '~/lib/i18n'
import { useFileExists } from '~/lib/workspaceFiles'
import { InlineCode } from './InlineCode'
import { faviconOf, parseWebSearchResults } from './searchResults'
import type { AgentStep } from '~/lib/agentProvider'
import type { OnOpenStep, OnOpenFile } from './types'
import { TerminalStepCard } from './steps/TerminalStepCard'
import { ToolCallStepCard } from './steps/ToolCallStepCard'
import { ArtifactStepCard } from './steps/ArtifactStepCard'
import { AuthConfirmStepCard } from './steps/AuthConfirmStepCard'
import LoadSkillIcon from '~/assets/icons/load-skill.svg?react'
import SearchIcon from '~/assets/icons/search.svg?react'
import MemoryIcon from '~/assets/icons/memory.svg?react'
import JumpIcon from '~/assets/icons/jump.svg?react'
import GlobeIcon from '~/assets/files/web.svg?react'

/**
 * Shared shell for single-line step cards: leading icon + title + trailing
 * jump chevron. Clicking opens the workspace rail via `onClick`. When
 * `disabled` (e.g. a file whose workspace entry was deleted) it renders as a
 * non-interactive card — no chevron, `cursor-not-allowed`, muted title — with
 * an optional trailing `note` (e.g. "this file was deleted").
 */
function StepCardShell({
  icon,
  children,
  onClick,
  disabled = false,
  note,
  maxWidthClass = 'max-w-full'
}: {
  icon: ReactNode
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  note?: ReactNode
  maxWidthClass?: string
}) {
  if (disabled) {
    return (
      <div
        className={`flex w-fit cursor-not-allowed items-center gap-2 rounded-xl border border-msa-line-1 bg-msa-fill-1 px-3 py-2 text-left ${maxWidthClass}`}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
          {icon}
        </span>
        <Typography.Text
          ellipsis={{ tooltip: { title: children } }}
          className="min-w-0 flex-1 !text-sm !text-msa-text-3"
        >
          {children}
        </Typography.Text>
        {note && (
          <span className="shrink-0 text-xs text-msa-text-danger">{note}</span>
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
        ellipsis={{ tooltip: { title: children } }}
        className="min-w-0 flex-1 !text-sm !text-msa-text-1"
      >
        {children}
      </Typography.Text>
      <JumpIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
    </button>
  )
}

/** File step card ("modified: x" / "read: x") with LIVE existence: a webui
 * rename/delete flips it to the disabled "deleted" card immediately (via the
 * workspace file-set context), no reload needed. */
function FileStepCard({
  path,
  label,
  serverExists,
  onOpen
}: {
  path: string
  label: string
  serverExists: boolean
  onOpen: () => void
}) {
  const { t } = useT()
  const exists = useFileExists(path, serverExists)
  const icon = <FileTypeIcon name={path} className="h-4 w-4" />
  if (!exists) {
    return (
      <StepCardShell icon={icon} disabled note={t.home.fileDeleted}>
        <span className="align-middle">{label}：</span>
        <InlineCode>{path}</InlineCode>
      </StepCardShell>
    )
  }
  return (
    <StepCardShell icon={icon} onClick={onOpen}>
      <span className="align-middle">{label}：</span>
      <InlineCode>{path}</InlineCode>
    </StepCardShell>
  )
}

/** Human label + detail for a tool that is CURRENTLY executing (status
 * "running"). Reuses the finished-card i18n strings; the spinner conveys the
 * in-progress state, so no separate "…ing" wording is needed. */
function runningDescriptor(
  kind: string,
  meta: Record<string, unknown>,
  s: ReturnType<typeof useT>['t']['chat']
): { label: string; detail: string } {
  switch (kind) {
    case 'search':
      return String(meta.scope ?? '') === 'files'
        ? { label: s.stepSearchFiles, detail: String(meta.query ?? '') }
        : { label: s.stepSearch, detail: String(meta.query ?? '') }
    case 'browser':
      return { label: s.stepBrowser, detail: String(meta.title ?? meta.url ?? '') }
    case 'terminal':
      return { label: s.stepTerminal, detail: '' }
    case 'file_read':
      return { label: s.stepFileRead, detail: String(meta.path ?? '') }
    case 'file_write':
      return { label: s.stepFileWrite, detail: String(meta.path ?? '') }
    case 'file_edit':
      return { label: s.stepFileEdit, detail: String(meta.path ?? '') }
    case 'skill_load':
      return { label: s.stepLoadSkill, detail: String(meta.name ?? '') }
    case 'memory':
      return {
        label: String(meta.action ?? '') === 'read' ? s.stepMemoryRead : s.stepMemory,
        detail: ''
      }
    default:
      return { label: s.stepInvoke, detail: String(meta.name ?? '') }
  }
}

/** Live "executing" card shown from tool_call_started until the result frame
 * (same call_id) replaces it — so a slow tool (e.g. web_search) gives immediate
 * feedback instead of a blank gap. A leading spinner marks the in-progress
 * state; the label says which tool is running. */
function RunningStepCard({ step }: { step: AgentStep }) {
  const { t } = useT()
  const { label, detail } = runningDescriptor(step.kind, step.meta, t.chat)
  const tip = detail ? `${label} ${detail}` : label
  return (
    <div className="flex w-fit max-w-full items-center gap-2 rounded-xl border border-msa-line-1 bg-msa-fill-1 px-3 py-2 text-left">
      <span
        className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-[1.5px] border-msa-line-1 border-t-msa-text-brand1"
        aria-hidden
      />
      <Typography.Text
        ellipsis={{ tooltip: { title: tip } }}
        className="min-w-0 flex-1 !text-sm !text-msa-text-2"
      >
        <span className="align-middle">{label}</span>
        {detail ? (
          <>
            {' '}
            <InlineCode>{detail}</InlineCode>
          </>
        ) : null}
      </Typography.Text>
    </div>
  )
}

/** Dispatches a step to the correct card by its kind. */
export function StepCard({
  step,
  onOpenStep,
  onOpenFile,
  isLast
}: {
  step: AgentStep
  onOpenStep?: OnOpenStep
  onOpenFile?: OnOpenFile
  /** Whether this step is the last meaningful part of its message — accordion
   * cards default expanded while last, auto-collapse once newer parts arrive. */
  isLast?: boolean
}) {
  const { t } = useT()
  const meta = step.meta
  const open = () => onOpenStep?.(step)

  // A tool still executing (emitted on tool_call_started): show a live
  // "running" card until its result frame (same call_id) replaces it in place.
  if (meta.status === 'running') return <RunningStepCard step={step} />

  switch (step.kind) {
    case 'terminal':
      return (
        <TerminalStepCard step={step} onOpenStep={onOpenStep} isLast={isLast} />
      )
    case 'artifact':
      return <ArtifactStepCard step={step} onOpenStep={onOpenStep} />
    case 'authorization': {
      // History-replayed approved authorizations (no request_id) don't render —
      // the adjacent tool_call step already shows the full invocation. LIVE
      // approved cards (request_id present) stay visible while the tool runs;
      // agentProvider replaces them in place when the result step arrives.
      const authState = (meta.state as string) ?? 'pending'
      if (authState === 'approved' && !meta.request_id) return null
      return <AuthConfirmStepCard step={step} isLast={isLast} />
    }
    case 'tool_call':
      return (
        <ToolCallStepCard step={step} onOpenStep={onOpenStep} isLast={isLast} />
      )
    case 'skill_load':
      return (
        <ToolCallStepCard
          step={step}
          isLast={isLast}
          icon={
            typeof meta.icon === 'string' ? (
              <img src={meta.icon} alt="" className="h-4 w-4" />
            ) : (
              <LoadSkillIcon className="h-4 w-4 text-msa-text-brand1" />
            )
          }
          title={
            <>
              <span className="align-middle">{t.chat.stepLoadSkill}</span>{' '}
              <InlineCode>{String(meta.name ?? '')}</InlineCode>
            </>
          }
          titleText={`${t.chat.stepLoadSkill} ${String(meta.name ?? '')}`}
        />
      )
    case 'file_read':
    case 'file_write':
    case 'file_edit': {
      const path = String(meta.path ?? '')
      // Distinct label per file operation: read / full-content write /
      // in-place edit — the three render as distinguishable cards.
      const label =
        step.kind === 'file_read'
          ? t.chat.stepFileRead
          : step.kind === 'file_edit'
            ? t.chat.stepFileEdit
            : t.chat.stepFileWrite
      // Errored file steps (permission denied, interrupted, etc.) render as a
      // ToolCallStepCard accordion showing what was attempted + the error.
      if (meta.status === 'error') {
        return (
          <ToolCallStepCard
            step={step}
            onOpenStep={onOpenStep}
            isLast={isLast}
          />
        )
      }
      return (
        <FileStepCard
          path={path}
          label={label}
          // Server-baked flag from history replay — the live workspace set
          // (when loaded) overrides it inside FileStepCard.
          serverExists={meta.exists !== false}
          onOpen={() => (onOpenFile ? onOpenFile(path) : open())}
        />
      )
    }
    case 'browser': {
      const title = String(meta.title ?? meta.url ?? '')
      return (
        <ToolCallStepCard
          step={step}
          isLast={isLast}
          icon={<GlobeIcon className="h-4 w-4" />}
          title={
            <>
              <span className="align-middle">{t.chat.stepBrowser}</span>{' '}
              <InlineCode>{title}</InlineCode>
            </>
          }
          titleText={`${t.chat.stepBrowser} ${title}`}
        />
      )
    }
    case 'search': {
      const query = String(meta.query ?? '')
      // File-scoped searches (grep/glob) keep the inline accordion; WEB
      // searches are a one-line card that opens the result list in the right
      // rail (globe icon, result count + stacked favicons once finished).
      if (String(meta.scope ?? '') === 'files') {
        return (
          <ToolCallStepCard
            step={step}
            isLast={isLast}
            icon={<SearchIcon className="h-4 w-4" />}
            title={
              <>
                <span className="align-middle">{t.chat.stepSearchFiles}</span>{' '}
                <InlineCode>{query}</InlineCode>
              </>
            }
            titleText={`${t.chat.stepSearchFiles} ${query}`}
          />
        )
      }
      const results = parseWebSearchResults(meta.result)
      const favicons = results
        .map((r) => faviconOf(r.url))
        .filter(Boolean)
        .slice(0, 3)
      return (
        <StepCardShell icon={<GlobeIcon className="h-4 w-4" />} onClick={open}>
          <span className="align-middle">{t.chat.stepSearch}</span>{' '}
          <InlineCode>{query}</InlineCode>
          {results.length > 0 && (
            <>
              {' '}
              <span className="align-middle">
                {t.chat.searchedPages.replace('{n}', String(results.length))}
              </span>
              <span className="ml-1.5 inline-flex items-center align-middle">
                {favicons.map((src, i) => (
                  <img
                    key={i}
                    src={src}
                    alt=""
                    className={`h-4 w-4 rounded-full border border-msa-line-1 bg-msa-bg-1 ${
                      i > 0 ? '-ml-1.5' : ''
                    }`}
                    onError={(e) => {
                      ;(e.target as HTMLImageElement).style.display = 'none'
                    }}
                  />
                ))}
              </span>
            </>
          )}
        </StepCardShell>
      )
    }
    case 'memory': {
      const label =
        String(meta.action ?? '') === 'read'
          ? t.chat.stepMemoryRead
          : t.chat.stepMemory
      return (
        <ToolCallStepCard
          step={step}
          isLast={isLast}
          icon={<MemoryIcon className="h-4 w-4" />}
          title={label}
        />
      )
    }
    default:
      return null
  }
}
