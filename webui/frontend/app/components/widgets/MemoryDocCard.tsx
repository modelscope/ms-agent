import { App, Button, Drawer, Segmented, Tooltip } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import { EmptyState } from '~/components/common/EmptyState'
import { Markdown } from '~/components/common/Markdown'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Project } from '~/lib/types'
import { WidgetCard } from './WidgetCard'
import MemoryIcon from '~/assets/icons/memory.svg?react'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import ViewIcon from '~/assets/icons/view.svg?react'

/** Which face of the draft the drawer shows: the editor or its rendered form. */
type DraftView = 'edit' | 'preview'

/**
 * Memory card for `memory_backend === 'file'`.
 *
 * That backend keeps memory as ONE markdown file (`MEMORY.md`) which the agent
 * reads every turn — not a list of rows. So the card previews the rendered
 * document and edits it wholesale in a drawer, instead of the read-only
 * per-row list the vector backend gets (see MemoryCard).
 */
export function MemoryDocCard({ project }: { project: Project }) {
  const { t } = useT()
  const { message } = App.useApp()
  const [content, setContent] = useState('')
  // null = not loaded yet (skeleton); '' = loaded and genuinely empty.
  const [loaded, setLoaded] = useState(false)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [view, setView] = useState<DraftView>('edit')
  const [saving, setSaving] = useState(false)
  // Reset/Save stay disabled until the draft diverges from what is stored.
  const dirty = draft !== content

  const refresh = useCallback(() => {
    api
      .getMemoryDoc(project.id, { silent: true })
      .then((d) => setContent(d.content ?? ''))
      .catch(() => setContent(''))
      .finally(() => setLoaded(true))
  }, [project.id])

  useEffect(() => {
    setLoaded(false)
    refresh()
  }, [refresh])

  const openEditor = () => {
    setDraft(content)
    setView('edit')
    setOpen(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      const saved = await api.putMemoryDoc(project.id, draft)
      setContent(saved.content ?? '')
      setOpen(false)
      message.success(t.widgets.memorySaved)
    } finally {
      setSaving(false)
    }
  }

  if (!project.memory_enabled) {
    return (
      <WidgetCard
        title={t.widgets.memoryTitle}
        icon={<MemoryIcon className="h-5 w-5" />}
        badge={t.newProject.backendFile}
      >
        <div className="flex items-center justify-center text-xs leading-relaxed text-msa-text-3">
          {t.widgets.memoryDisabled}
        </div>
      </WidgetCard>
    )
  }

  return (
    <>
      <WidgetCard
        title={t.widgets.memoryTitle}
        icon={<MemoryIcon className="h-5 w-5" />}
        // Marks this as the FILE shape of memory (one markdown document).
        badge={t.newProject.backendFile}
        onEdit={loaded ? openEditor : undefined}
        className="flex-initial min-h-0 flex flex-col overflow-hidden"
        bodyClassName="flex-1 overflow-y-auto"
      >
        {!loaded ? (
          <DeferredSkeleton rows={6} className="py-1" />
        ) : content.trim() ? (
          <Markdown content={content} />
        ) : (
          <EmptyState
            size="sm"
            description={t.widgets.memoryDocEmpty}
            className="!py-2"
          />
        )}
      </WidgetCard>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t.widgets.memoryDocDrawerTitle}
        placement="right"
        size="min(720px, 92vw)"
        footer={
          /* Cancel / Reset / Save, matching the MCP JSON editor: cancel always
             available, the other two only once the draft actually differs from
             what is stored. */
          <div className="flex items-center justify-end gap-2">
            <Button onClick={() => setOpen(false)}>{t.widgets.cancel}</Button>
            <Button disabled={!dirty} onClick={() => setDraft(content)}>
              {t.resources.jsonReset}
            </Button>
            <Button
              type="primary"
              loading={saving}
              disabled={!dirty}
              onClick={save}
            >
              {t.widgets.save}
            </Button>
          </div>
        }
      >
        <div className="flex h-full min-h-0 flex-col gap-2">
          <div className="flex shrink-0 items-center gap-2">
            <span className="min-w-0 flex-1 text-xs text-msa-text-3">
              {t.widgets.memoryDocHint}
            </span>
            {/* Edit / preview toggle — same control and icons the skill viewer
                uses, so switching views feels identical across the app. The
                draft is what gets previewed, so unsaved edits render live. */}
            <Segmented<DraftView>
              size="small"
              value={view}
              onChange={setView}
              options={[
                {
                  value: 'edit',
                  icon: (
                    <Tooltip title={t.skillDetail.viewCode}>
                      <TerminalIcon className="h-4 w-4" />
                    </Tooltip>
                  )
                },
                {
                  value: 'preview',
                  icon: (
                    <Tooltip title={t.skillDetail.viewPreview}>
                      <ViewIcon className="h-4 w-4" />
                    </Tooltip>
                  )
                }
              ]}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-msa-line-1">
            {view === 'edit' ? (
              <CodeEditor
                value={draft}
                onChange={setDraft}
                language="markdown"
                height="100%"
                fullFeatures
              />
            ) : (
              <div className="h-full overflow-y-auto px-4 py-3">
                {draft.trim() ? (
                  <Markdown content={draft} />
                ) : (
                  <EmptyState
                    size="sm"
                    description={t.widgets.memoryDocEmpty}
                    className="!py-2"
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </Drawer>
    </>
  )
}
