import { LoadingOutlined } from '@ant-design/icons'
import { App, Button, Popconfirm, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { IconButton } from '~/components/common/IconButton'
import { EmptyState } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
import { useOnProjectSettingsChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { MemoryItem, MemoryStatus, Project } from '~/lib/types'
import { WidgetCard } from './WidgetCard'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import MemoryIcon from '~/assets/icons/memory.svg?react'
import DeleteIcon from '~/assets/icons/delete.svg?react'

interface Props {
  project: Project
}

/** "provider/model" identity chip text for the resolved embedder. */
function embedderLabel(status: MemoryStatus | null): string | null {
  const e = status?.embedder
  if (!e?.model) return null
  const model = e.model.split('/').pop() || e.model
  return e.mode === 'local' ? `local · ${model}` : `${e.provider} · ${model}`
}

/** The chip is truncated in the header; the tooltip carries the full identity,
 * including the width the store was built at. */
function embedderTitle(status: MemoryStatus | null): string {
  const e = status?.embedder
  if (!e?.model) return ''
  const who = e.mode === 'local' ? 'local' : (e.provider ?? '')
  const dims = e.dimension ? ` · ${e.dimension}d` : ''
  return `${who} · ${e.model}${dims}`
}

export function MemoryCard({ project }: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const [items, setItems] = useState<MemoryItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [status, setStatus] = useState<MemoryStatus | null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  // Why the list could not be read. Distinguishing this from "no memories yet"
  // matters: an unusable vector backend (no embedder, identity mismatch)
  // must read as a problem with a remedy, not as an empty store forever.
  const [error, setError] = useState('')

  const memoryOn = project.memory_enabled

  const refresh = useCallback(() => {
    if (!memoryOn) {
      setItems([])
      return
    }
    api
      // silent: failures are rendered in the card, so a global toast on every
      // mount would just be a duplicate.
      .listMemoryItems(project.id, { silent: true })
      .then((rows) => {
        setItems(rows)
        setError('')
      })
      .catch((e: unknown) => {
        setItems([])
        setError(
          (e instanceof Error && e.message) || t.widgets.memoryLoadFailed
        )
      })
      .finally(() => setLoaded(true))
    // Health surface: embedder identity, config errors, last ingest outcome.
    api
      .getMemoryStatus(project.id, { silent: true })
      .then(setStatus)
      .catch(() => setStatus(null))
    // Re-checked whenever the EMBEDDER choice changes, not just on mount: that
    // choice decides whether the store is still readable at all, so editing it
    // has to re-run the health check — otherwise the card keeps showing a
    // healthy list for a store the project can no longer open, until something
    // else happens to reload the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    project.id,
    memoryOn,
    project.memory_embed_mode,
    project.memory_embed_provider_id,
    project.memory_embed_model
  ])
  useEffect(refresh, [refresh])
  // Re-fetch when the edit modal saves (the user may have changed the embed
  // model or toggled memory on/off — the status endpoint reflects the new
  // config immediately).
  useOnProjectSettingsChanged(refresh)

  // A background ingest may be in flight right after a turn, and re-embedding
  // a store takes as long as the embedder takes — poll while the server reports
  // either so the result appears without a manual refresh.
  useEffect(() => {
    const state = status?.ingest?.state
    const busy =
      status?.rebuilding || state === 'scheduled' || state === 'running'
    if (!busy) return
    const timer = setTimeout(refresh, 2000)
    return () => clearTimeout(timer)
  }, [status, refresh])

  const deleteItem = async (id: string) => {
    await api.deleteMemoryItem(project.id, id)
    refresh()
  }

  const rebuild = async () => {
    setRebuilding(true)
    try {
      const result = await api.rebuildMemory(project.id)
      // Say what actually happened: entries are carried over now, and a store
      // that already speaks the current model is left alone entirely.
      message.success(
        result.reused
          ? t.widgets.memoryRebuildReused
          : t.widgets.memoryRebuilt.replace('{n}', String(result.migrated))
      )
      refresh()
    } catch {
      // surfaced by the global toast
    } finally {
      setRebuilding(false)
    }
  }

  if (!memoryOn) {
    return (
      <WidgetCard
        title={t.widgets.memoryTitle}
        icon={<MemoryIcon className="h-5 w-5" />}
        badge={t.newProject.backendVector}
      >
        <div className="flex items-center justify-center text-xs text-msa-text-3 leading-relaxed">
          {t.widgets.memoryDisabled}
        </div>
      </WidgetCard>
    )
  }

  const chip = embedderLabel(status)
  const ingest = status?.ingest
  const mismatch = status?.error?.code === 'embedder_mismatch'
  const ingestNote =
    ingest?.state === 'scheduled' || ingest?.state === 'running' ? (
      <span className="text-xs text-msa-text-3">
        {t.widgets.memoryIngesting}
      </span>
    ) : ingest?.state === 'error' ? (
      <Tooltip title={ingest.error ?? ''}>
        <span className="text-xs text-msa-text-danger">
          {t.widgets.memoryIngestFailed}
        </span>
      </Tooltip>
    ) : null

  return (
    <WidgetCard
      title={t.widgets.memoryTitle}
      icon={<MemoryIcon className="h-5 w-5" />}
      count={items.length}
      // This card is the VECTOR shape of memory; the tag says so, since the file
      // backend gets a completely different (document) UI.
      badge={t.newProject.backendVector}
      // The embedder belongs to the header, next to what it produced: it names
      // the model every entry below was embedded with, and putting it under a
      // scrolling list buried it.
      extra={
        chip ? (
          <Tooltip title={embedderTitle(status)}>
            <span className="max-w-[220px] truncate text-xs font-normal text-msa-text-3">
              {chip}
            </span>
          </Tooltip>
        ) : undefined
      }
      className="flex-initial min-h-0 flex flex-col overflow-hidden"
      bodyClassName="flex-1 overflow-y-auto"
    >
      {!loaded ? (
        <DeferredSkeleton rows={6} className="py-1" />
      ) : status?.rebuilding ? (
        /* Mid-rebuild the entries are being written into a staging store, so
           neither the old list nor the mismatch error is the truth. */
        <div className="flex items-center justify-center gap-2 rounded-lg bg-msa-fill-2 px-3 py-3 text-xs text-msa-text-3">
          <LoadingOutlined />
          {t.widgets.memoryRebuilding}
        </div>
      ) : error || status?.error ? (
        <div className="rounded-lg bg-msa-fill-2 px-3 py-3">
          <p className="m-0 text-xs font-medium text-msa-text-danger">
            {t.widgets.memoryLoadFailed}
          </p>
          {/* The backend's own reason, verbatim — it names the actual cause
              (identity mismatch, missing local model, …), the only thing that
              tells the user what to go fix. */}
          <p className="m-0 mt-1 text-xs leading-relaxed break-words text-msa-text-3">
            {status?.error?.message || error}
          </p>
          {mismatch && (
            /* The mismatch's remedy: start over with the current embedder.
               The old store is moved aside server-side, never deleted. */
            <Popconfirm
              title={t.widgets.memoryRebuildConfirm}
              okText={t.widgets.memoryRebuild}
              cancelText={t.workspace.cancel}
              onConfirm={rebuild}
            >
              <Button size="small" danger loading={rebuilding} className="mt-2">
                {t.widgets.memoryRebuild}
              </Button>
            </Popconfirm>
          )}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          size="sm"
          description={t.widgets.memoryEmpty}
          className="!py-2"
        />
      ) : (
        /* Read-only list: vector memories are produced by the agent's own fact
           extraction during conversation, so there is no hand-authoring here —
           the only action is removing one the agent got wrong. (The file backend
           is the editable one; see MemoryDocCard.) */
        <div className="space-y-2.5">
          {items.map((item) => (
            <div
              key={item.id}
              className="group flex items-center gap-2 rounded-lg bg-msa-fill-2 px-3 py-3"
            >
              {/* Clamped to two lines, so the full fact needs a tooltip to stay
                  readable. antd's `ellipsis` measures the node and only attaches
                  one when the text is ACTUALLY cut — a plain `title` would pop up
                  on short memories too. */}
              <Typography.Paragraph
                className="!m-0 flex-1 !text-sm !leading-relaxed !text-msa-text-2"
                ellipsis={{ rows: 2, tooltip: { title: item.content } }}
              >
                {item.content}
              </Typography.Paragraph>
              <Popconfirm
                title={t.widgets.deleteMemory}
                okText={t.workspace.delete}
                cancelText={t.workspace.cancel}
                onConfirm={() => deleteItem(item.id)}
              >
                <Tooltip title={t.widgets.delete}>
                  <IconButton
                    icon={<DeleteIcon className="h-5 w-5" />}
                    size="xs"
                    variant="ghost"
                    className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 hover:!text-msa-text-danger"
                  />
                </Tooltip>
              </Popconfirm>
            </div>
          ))}
        </div>
      )}
      {/* Footer: transient ingest states only (updating / failed), so it is
          absent in the normal case. Totals are in the header count, and the
          embedder is in the header too. */}
      {loaded && ingestNote && (
        <div className="mt-2 flex items-center justify-end border-t border-msa-line-1 pt-2">
          {ingestNote}
        </div>
      )}
    </WidgetCard>
  )
}
