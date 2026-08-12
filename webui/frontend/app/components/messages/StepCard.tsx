import { Typography } from 'antd'
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
import { StepCardShell, StepInProgressRow } from './steps/StepCardShell'
import { AuthConfirmStepCard } from './steps/AuthConfirmStepCard'
import LoadSkillIcon from '~/assets/icons/load-skill.svg?react'
import SearchIcon from '~/assets/icons/search.svg?react'
import MemoryIcon from '~/assets/icons/memory.svg?react'
import JumpIcon from '~/assets/icons/jump.svg?react'
import GlobeIcon from '~/assets/icons/globe.svg?react'

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
      <StepCardShell
        icon={icon}
        disabled
        note={t.home.fileDeleted}
        tipText={`${label}：${path}`}
      >
        <span className="align-middle">{label}：</span>
        <InlineCode>{path}</InlineCode>
      </StepCardShell>
    )
  }
  return (
    <StepCardShell icon={icon} onClick={onOpen} tipText={`${label}：${path}`}>
      <span className="align-middle">{label}：</span>
      <InlineCode>{path}</InlineCode>
    </StepCardShell>
  )
}

/** One file row INSIDE the multi-file wrapper card (no border of its own — the
 * wrapper owns the border; the row is just a clickable line with hover bg and
 * its own live deleted state). */
function MultiFileRow({
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
  const inner = (
    <>
      <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
        {icon}
      </span>
      <Typography.Text
        ellipsis={{ tooltip: { title: `${label}：${path}` } }}
        className={`min-w-0 flex-1 !text-sm ${
          exists ? '!text-msa-text-1' : '!text-msa-text-3'
        }`}
      >
        <span className="align-middle">{label}：</span>
        <InlineCode>{path}</InlineCode>
      </Typography.Text>
    </>
  )
  if (!exists) {
    return (
      <div className="flex w-full cursor-not-allowed items-center gap-2 rounded-lg px-2 py-1.5 text-left">
        {inner}
        <span className="shrink-0 text-xs text-msa-text-danger">
          {t.home.fileDeleted}
        </span>
      </div>
    )
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-2 py-1.5 text-left transition-colors hover:bg-msa-fill-4"
    >
      {inner}
      <JumpIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
    </button>
  )
}

/** Wrapper for a SINGLE tool call that read/edited SEVERAL files: one bordered
 * card holding the file rows flat inside, so it reads as one tool invocation
 * (matching the "used 1 tool" count) rather than N separate tool cards. */
function MultiFileStepCard({
  paths,
  label,
  serverExists,
  onOpen
}: {
  paths: string[]
  label: string
  serverExists: boolean
  onOpen: (path: string) => void
}) {
  return (
    <div className="flex w-fit max-w-full flex-col gap-0.5 rounded-xl border border-msa-line-1 bg-msa-fill-1 p-1.5">
      {paths.map((p, i) => (
        <MultiFileRow
          key={`${p}-${i}`}
          path={p}
          label={label}
          serverExists={serverExists}
          onOpen={() => onOpen(p)}
        />
      ))}
    </div>
  )
}

/** Dispatches a step to the correct card by its kind.
 *
 * A step still executing (`meta.status === "running"`, emitted on
 * tool_call_started) is NOT a card of its own: it dispatches to the very card
 * its result will land in, and that card renders its own in-progress state (a
 * spinner in place of its leading glyph). One card per tool call, from start to
 * result — no separate placeholder that swaps out mid-flight. */
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
  const running = meta.status === 'running'

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
    case 'skill_list': {
      // Same SDK tool for both: a `query` makes it a search, without one it's a
      // plain catalog listing.
      const query = String(meta.query ?? '')
      const label = query ? t.chat.stepSkillSearch : t.chat.stepSkillList
      return (
        <ToolCallStepCard
          step={step}
          isLast={isLast}
          icon={<LoadSkillIcon className="h-4 w-4 text-msa-text-brand1" />}
          title={
            query ? (
              <>
                <span className="align-middle">{label}</span>{' '}
                <InlineCode>{query}</InlineCode>
              </>
            ) : (
              label
            )
          }
          titleText={query ? `${label} ${query}` : label}
        />
      )
    }
    case 'skill_manage': {
      const action = String(meta.action ?? '')
      const label =
        action === 'create'
          ? t.chat.stepSkillCreate
          : action === 'edit'
            ? t.chat.stepSkillEdit
            : action === 'delete'
              ? t.chat.stepSkillDelete
              : t.chat.stepSkillManage
      const skill = String(meta.skill ?? '')
      return (
        <ToolCallStepCard
          step={step}
          isLast={isLast}
          icon={<LoadSkillIcon className="h-4 w-4 text-msa-text-brand1" />}
          title={
            skill ? (
              <>
                <span className="align-middle">{label}</span>{' '}
                <InlineCode>{skill}</InlineCode>
              </>
            ) : (
              label
            )
          }
          titleText={skill ? `${label} ${skill}` : label}
        />
      )
    }
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
      // The accordion form of this card, used whenever the operation needs more
      // than a one-line row: the authorization ask (three decision buttons), a
      // refusal, or a failure (the error text). It keeps the file's identity —
      // that file type's glyph + the operation named on the path — instead of
      // falling back to "call tool file_system---write_file" plus a JSON blob.
      const askLabel =
        step.kind === 'file_read'
          ? t.chat.stepFileReadAsk
          : step.kind === 'file_edit'
            ? t.chat.stepFileEditAsk
            : t.chat.stepFileWriteAsk
      const fileAccordion = (
        <ToolCallStepCard
          step={step}
          onOpenStep={onOpenStep}
          isLast={isLast}
          icon={<FileTypeIcon name={path} className="h-4 w-4" />}
          title={
            <>
              <span className="align-middle">{askLabel}</span>{' '}
              <InlineCode>{path}</InlineCode>
            </>
          }
          titleText={`${askLabel} ${path}`}
        />
      )
      // An ask (or a refusal) has no room in a one-line row for the decision
      // buttons / the rejected badge. Titled with the pre-action verb, since
      // nothing has happened yet.
      const askState = String(meta.state ?? '')
      if (askState === 'pending' || askState === 'rejected') return fileAccordion
      // In progress: "reading/writing/editing {path}", not the past-tense row.
      // Either the live `running` frame, or an ask already approved whose result
      // hasn't landed (what an attach replay hands back after a refresh).
      if (
        running ||
        (askState === 'approved' && !!meta.request_id && !meta.result)
      ) {
        return <StepInProgressRow step={step} />
      }
      // Failed (interrupted, permission denied, write error …): the accordion
      // shows what was attempted plus the error, under a "call failed" badge.
      if (meta.status === 'error') return fileAccordion
      // A multi-file read/edit is ONE tool call: wrap its files in a single
      // bordered card (rows flat inside), so it reads as one invocation and
      // matches the "used N tools" count — not N separate tool cards. Each row
      // is still individually clickable + deleted-flagged.
      //
      // SEVERAL files, though: the tool also accepts `paths` with a single entry,
      // and wrapping that produced a visibly different card from the same
      // operation called with `path` — an inset borderless row inside a frame,
      // instead of the normal one-line card. One file, one plain card.
      const multi = Array.isArray(meta.paths)
        ? (meta.paths as unknown[]).map(String).filter(Boolean)
        : []
      if (multi.length > 1) {
        return (
          <MultiFileStepCard
            paths={multi}
            label={label}
            serverExists={meta.exists !== false}
            onOpen={(p) => (onOpenFile ? onOpenFile(p) : open())}
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
      // An ask (or a refusal) needs the accordion: room for the three decision
      // buttons / the rejected badge, which a one-line row has no space for. The
      // ask lands on THIS card rather than a generic "call tool" one (backend
      // _AUTH_INLINE_KINDS), so the user reads the query, not `web_search---x`.
      const askState = String(meta.state ?? '')
      if (askState === 'pending' || askState === 'rejected') {
        return (
          <ToolCallStepCard
            step={step}
            isLast={isLast}
            icon={<GlobeIcon className="h-4 w-4" />}
            title={
              <>
                <span className="align-middle">{t.chat.stepSearch}</span>{' '}
                <InlineCode>{query}</InlineCode>
              </>
            }
            titleText={`${t.chat.stepSearch} ${query}`}
          />
        )
      }
      // Still searching: the one-line row states it's in progress and is NOT
      // openable — there is no result list behind it yet. Two ways to be here:
      // the live `running` frame, OR an ASK already approved whose result hasn't
      // landed (what an attach replay after a page refresh hands back — those
      // frames carry the resolved ask, not a `running` status).
      if (
        running ||
        (askState === 'approved' && !!meta.request_id && !meta.result)
      ) {
        return <StepInProgressRow step={step} />
      }
      const favicons = results
        .map((r) => faviconOf(r.url))
        .filter(Boolean)
        .slice(0, 3)
      // A refusal is NOT a failure: a denied call's errored result reads "Tool
      // call denied", so it gets the rejection wording in the muted tone — red
      // "call failed" is reserved for searches that actually tried and broke
      // (timeout, interruption, upstream error).
      const denied =
        askState === 'rejected' ||
        (meta.status === 'error' &&
          /denied/i.test(String(meta.error ?? meta.result ?? '')))
      const failed = meta.status === 'error' && !denied
      return (
        <StepCardShell
          icon={<GlobeIcon className="h-4 w-4" />}
          onClick={open}
          // The outcome belongs on the ROW itself — the error text only lives in
          // the rail, which the user has to open to see.
          note={
            denied
              ? t.chat.authRejected
              : failed
                ? t.chat.callFailed
                : undefined
          }
          noteTone={denied ? 'muted' : 'danger'}
          tipText={
            results.length > 0
              ? `${t.chat.stepSearch} ${query} ${t.chat.searchedPages.replace(
                  '{n}',
                  String(results.length)
                )}`
              : `${t.chat.stepSearch} ${query}`
          }
        >
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
