import { App, Button, Popconfirm, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { IconButton } from '~/components/common/IconButton'
import { EmptyState } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, memoryOn])
  useEffect(refresh, [refresh])

  // A background ingest may be in flight right after a turn — poll briefly
  // while the server reports scheduled/running so the new rows appear without
  // a manual refresh.
  useEffect(() => {
    const state = status?.ingest?.state
    if (state !== 'scheduled' && state !== 'running') return
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
      await api.rebuildMemory(project.id)
      message.success(t.widgets.memoryRebuilt)
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

  return (
    <WidgetCard
      title={t.widgets.memoryTitle}
      icon={<MemoryIcon className="h-5 w-5" />}
      count={items.length}
      // This card is the VECTOR shape of memory; the tag says so, since the file
      // backend gets a completely different (document) UI.
      badge={t.newProject.backendVector}
      // Embedder identity in the top-right, next to the title — it's metadata
      // about the whole store, so it reads better as a header chip than as a
      // footer that scrolls with (and gets mistaken for) the memory rows.
      extra={
        chip ? (
          <Typography.Text
            className="text-msa-text-3"
            ellipsis={{
              tooltip: { title: chip }
            }}
          >
            <span className="text-xs">{chip}</span>
          </Typography.Text>
        ) : undefined
      }
      className="flex-initial min-h-0 flex flex-col overflow-hidden"
      bodyClassName="flex-1 overflow-y-auto"
    >
      {!loaded ? (
        <DeferredSkeleton rows={6} className="py-1" />
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
                    icon={<DeleteIcon className="h-4 w-4" />}
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
      {/* Footer: transient ingest states only (updating / failed). The embedder
          identity moved to the header chip; the count is already in the title. */}
      {loaded &&
        (ingest?.state === 'scheduled' ||
          ingest?.state === 'running' ||
          ingest?.state === 'error') && (
          <div className="mt-2 flex items-center justify-end border-t border-msa-line-1 pt-2">
            {ingest.state === 'error' ? (
              <Tooltip title={ingest.error ?? ''}>
                <span className="shrink-0 text-xs text-msa-text-danger">
                  {t.widgets.memoryIngestFailed}
                </span>
              </Tooltip>
            ) : (
              <span className="shrink-0 text-xs text-msa-text-3">
                {t.widgets.memoryIngesting}
              </span>
            )}
          </div>
        )}
    </WidgetCard>
  )
}
