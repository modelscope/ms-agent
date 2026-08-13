import type { ReactNode } from 'react'
import { IconButton } from '~/components/common/IconButton'
import { useT } from '~/lib/i18n'
import type { Dict } from '~/lib/i18n'
import type { AgentStep } from '~/lib/agentProvider'
import { faviconOf, hostOf, parseWebSearchResults } from './searchResults'
import JumpIcon from '~/assets/icons/jump.svg?react'
import GlobeIcon from '~/assets/icons/globe.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'

/** Human title for the rail header, per step kind. */
function titleFor(step: AgentStep, t: Dict): string {
  const meta = step.meta
  const s = (v: unknown) => String(v ?? '')
  switch (step.kind) {
    case 'file_read':
      return `${t.chat.stepFileRead}：${s(meta.path)}`
    case 'file_write':
      return `${t.chat.stepFileWrite}：${s(meta.path)}`
    case 'file_edit':
      return `${t.chat.stepFileEdit}：${s(meta.path)}`
    case 'skill_load':
      return `${t.chat.stepLoadSkill} ${s(meta.name)}`
    case 'skill_list':
      return meta.query
        ? `${t.chat.stepSkillSearch} ${s(meta.query)}`
        : t.chat.stepSkillList
    case 'skill_manage': {
      const action = s(meta.action)
      const label =
        action === 'create'
          ? t.chat.stepSkillCreate
          : action === 'edit'
            ? t.chat.stepSkillEdit
            : action === 'delete'
              ? t.chat.stepSkillDelete
              : t.chat.stepSkillManage
      return meta.skill ? `${label} ${s(meta.skill)}` : label
    }
    case 'browser':
      return `${t.chat.stepBrowser} ${s(meta.title ?? meta.url)}`
    case 'terminal':
      return t.chat.stepTerminal
    case 'search': {
      // Web searches title with the result count once finished (design spec:
      // "found N pages"); otherwise fall back to the query.
      const n = parseWebSearchResults(meta.result).length
      if (n > 0) return t.chat.searchedPages.replace('{n}', String(n))
      return `${t.chat.stepSearch} ${s(meta.query)}`
    }
    case 'memory':
      return s(meta.action) === 'read'
        ? t.chat.stepMemoryRead
        : t.chat.stepMemory
    case 'authorization':
      return t.chat.stepAuthTitle
    case 'artifact':
      return s(meta.name)
    default:
      return `${t.chat.stepInvoke} ${s(meta.tool ?? meta.name)}`
  }
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="text-xs font-medium uppercase tracking-wide text-msa-text-3">
        {label}
      </div>
      {children}
    </section>
  )
}

function CodeBlock({
  children,
  tone = 'default'
}: {
  children: ReactNode
  tone?: 'default' | 'error'
}) {
  return (
    <pre
      className={`m-0 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-msa-line-1 p-3 text-xs leading-relaxed ${
        tone === 'error'
          ? 'bg-msa-fill-error text-msa-text-danger'
          : 'bg-msa-fill-1 text-msa-text-1'
      }`}
    >
      {children}
    </pre>
  )
}

function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="w-fit break-all rounded-lg bg-msa-fill-2 px-2 py-1 text-sm text-msa-text-1">
      {children}
    </code>
  )
}

function EmptyHint({ label }: { label: string }) {
  return <div className="text-sm text-msa-text-3">{label}</div>
}

const asStr = (v: unknown): string => (typeof v === 'string' ? v : '')

const asRecord = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}

/**
 * Search result cards (web_search unified shape), per the design spec: each
 * card shows a site header (favicon + hostname + jump chevron), the page
 * title, and — when present — a clamped summary. The whole card opens the
 * url. Falls back to the raw payload (e.g. file_system grep/glob text) when
 * it isn't a `{results:[...]}` object.
 */
function SearchResults({ raw }: { raw: string }) {
  const results = parseWebSearchResults(raw)
  if (results.length === 0) {
    return <CodeBlock>{raw}</CodeBlock>
  }
  return (
    <div className="flex flex-col gap-3">
      {results.map((r, i) => {
        const host = hostOf(r.url)
        const favicon = faviconOf(r.url)
        const inner = (
          <>
            {/* Site header row, separated from the content by a divider */}
            <div className="flex items-center gap-2 border-b border-msa-line-1 px-3 py-2.5">
              {favicon ? (
                <img
                  src={favicon}
                  alt=""
                  className="h-4 w-4 rounded-full"
                  onError={(e) => {
                    ;(e.target as HTMLImageElement).style.display = 'none'
                  }}
                />
              ) : (
                <GlobeIcon className="h-4 w-4 text-msa-text-3" />
              )}
              <span className="min-w-0 flex-1 truncate text-xs text-msa-text-2">
                {host || r.url}
              </span>
              {r.url && (
                <JumpIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
              )}
            </div>
            <div className="px-3 py-3">
              {(r.title || r.url) && (
                <div className="text-sm font-medium text-msa-text-1">
                  {r.title || r.url}
                </div>
              )}
              {r.summary && (
                <div className="mt-1 line-clamp-3 whitespace-pre-line text-xs leading-relaxed text-msa-text-3">
                  {r.summary}
                </div>
              )}
            </div>
          </>
        )
        return r.url ? (
          <a
            key={i}
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1 transition-colors hover:bg-msa-fill-4"
          >
            {inner}
          </a>
        ) : (
          <div
            key={i}
            className="overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1"
          >
            {inner}
          </div>
        )
      })}
    </div>
  )
}

/** Extract readable file content from a read_file result (raw text, a
 * `{path: content}` map, or a `{type:"file_unchanged", message}` note). */
function fileReadContent(result: string): string {
  try {
    const obj = JSON.parse(result)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      const rec = obj as Record<string, unknown>
      if (typeof rec.message === 'string' && rec.type) return rec.message
      const strings = Object.values(rec).filter(
        (v): v is string => typeof v === 'string'
      )
      if (strings.length) return strings.join('\n\n')
    }
  } catch {
    /* not JSON — show as-is */
  }
  return result
}

/** Per-kind body: the same clicked-step data rendered differently by type. */
function StepDetailBody({ step, t }: { step: AgentStep; t: Dict }) {
  const meta = step.meta ?? {}
  const argRec = asRecord(meta.arguments)
  const hasArgs = Object.keys(argRec).length > 0
  const result = asStr(meta.result)
  const error = asStr(meta.error)
  const errorSection = error ? (
    <Section label={t.chat.detailError}>
      <CodeBlock tone="error">{error}</CodeBlock>
    </Section>
  ) : null

  switch (step.kind) {
    case 'search': {
      const query = asStr(meta.query)
      return (
        <>
          {query && (
            <Section label={t.chat.detailQuery}>
              <CodeBlock>{query}</CodeBlock>
            </Section>
          )}
          {result && (
            <Section label={t.chat.detailResults}>
              <SearchResults raw={result} />
            </Section>
          )}
          {errorSection}
          {!query && !result && !error && (
            <EmptyHint label={t.chat.detailEmpty} />
          )}
        </>
      )
    }
    case 'memory': {
      const content = asStr(argRec.content) || asStr(argRec.new_content)
      return (
        <>
          {content && (
            <Section label={t.chat.detailContent}>
              <CodeBlock>{content}</CodeBlock>
            </Section>
          )}
          {result && (
            <Section label={t.chat.detailResult}>
              <CodeBlock>{result}</CodeBlock>
            </Section>
          )}
          {errorSection}
          {!content && !result && !error && (
            <EmptyHint label={t.chat.detailEmpty} />
          )}
        </>
      )
    }
    case 'terminal': {
      const code =
        asStr(meta.code) || asStr(argRec.command) || asStr(argRec.code)
      return (
        <>
          {code && (
            <Section label={t.chat.detailCommand}>
              <CodeBlock>{code}</CodeBlock>
            </Section>
          )}
          {result && (
            <Section label={t.chat.detailOutput}>
              <CodeBlock>{result}</CodeBlock>
            </Section>
          )}
          {errorSection}
          {!code && !result && !error && (
            <EmptyHint label={t.chat.detailEmpty} />
          )}
        </>
      )
    }
    case 'file_read':
    case 'file_write':
    case 'file_edit': {
      // The path is already in the header title; show the body content.
      if (step.kind === 'file_read') {
        const content = fileReadContent(result)
        return (
          <>
            {content && (
              <Section label={t.chat.detailContent}>
                <CodeBlock>{content}</CodeBlock>
              </Section>
            )}
            {errorSection}
            {!content && !error && <EmptyHint label={t.chat.detailEmpty} />}
          </>
        )
      }
      // file_write carries a full-content write (`content`); file_edit a
      // diff-style old->new replacement. Argument names vary across tool
      // dialects, so alias them all; otherwise an edit shows nothing (it
      // carries no `content`).
      const content = asStr(argRec.content) || asStr(argRec.file_text)
      const oldText =
        asStr(argRec.old) || asStr(argRec.old_string) || asStr(argRec.old_str)
      const newText =
        asStr(argRec.new) || asStr(argRec.new_string) || asStr(argRec.new_str)
      const hasBody = !!(content || oldText || newText)
      return (
        <>
          {content && (
            <Section label={t.chat.detailContent}>
              <CodeBlock>{content}</CodeBlock>
            </Section>
          )}
          {!content && oldText && (
            <Section label={t.chat.detailBefore}>
              <CodeBlock>{oldText}</CodeBlock>
            </Section>
          )}
          {!content && newText && (
            <Section label={t.chat.detailAfter}>
              <CodeBlock>{newText}</CodeBlock>
            </Section>
          )}
          {result && (
            <Section label={t.chat.detailResult}>
              <CodeBlock>{result}</CodeBlock>
            </Section>
          )}
          {errorSection}
          {!hasBody && !result && !error && (
            <EmptyHint label={t.chat.detailEmpty} />
          )}
        </>
      )
    }
    default: {
      // Generic tool_call / browser / skill_load / artifact / authorization:
      // the full invocation as tool + arguments + result.
      const tool = asStr(meta.tool) || asStr(meta.name)
      const empty = !tool && !hasArgs && !result && !error
      return (
        <>
          {tool && (
            <Section label={t.chat.detailTool}>
              <InlineCode>{tool}</InlineCode>
            </Section>
          )}
          {hasArgs && (
            <Section label={t.chat.detailArguments}>
              <CodeBlock>{JSON.stringify(argRec, null, 2)}</CodeBlock>
            </Section>
          )}
          {result && (
            <Section label={t.chat.detailResult}>
              <CodeBlock>{result}</CodeBlock>
            </Section>
          )}
          {errorSection}
          {empty && <EmptyHint label={t.chat.detailEmpty} />}
        </>
      )
    }
  }
}

/**
 * Right-side squeezable rail showing the full detail of a clicked step card.
 * Mirrors the workspace rail (SessionRightRail) layout — a filling column with a
 * header (title + close) over a scrollable body — but is a dedicated component
 * that renders each tool kind (search / memory / terminal / file / generic)
 * differently, not the file workspace.
 */
export function StepDetailRail({
  step,
  onClose,
  clip = false
}: {
  step: AgentStep
  onClose: () => void
  /** Clip the scrollable body (overflow hidden) while the rail is animating, so
   * its content doesn't reflow or flash a scrollbar mid-transition. */
  clip?: boolean
}) {
  const { t } = useT()
  const title = titleFor(step, t)

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-msa-line-1 px-[20px] py-[16px]">
        <h3
          className="m-0 min-w-0 flex-1 truncate text-base font-semibold text-msa-text-1"
          title={title}
        >
          {title}
        </h3>
        <IconButton
          icon={<CloseIcon className="h-4 w-4" />}
          variant="tonal"
          size="sm"
          onClick={onClose}
        />
      </div>

      {/* Body */}
      <div
        className={`min-h-0 flex-1 p-5 ${clip ? 'overflow-hidden' : 'overflow-y-auto'}`}
      >
        <div className="flex flex-col gap-5">
          <StepDetailBody step={step} t={t} />
        </div>
      </div>
    </div>
  )
}
