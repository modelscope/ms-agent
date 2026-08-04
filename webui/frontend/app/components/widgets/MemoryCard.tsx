import { Button, Input, Popconfirm, Tooltip } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { IconButton } from '~/components/common/IconButton'
import { EmptyState } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { MemoryItem, Project } from '~/lib/types'
import { WidgetCard } from './WidgetCard'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import MemoryIcon from '~/assets/icons/memory.svg?react'
import EditIcon from '~/assets/icons/edit.svg?react'
import DeleteIcon from '~/assets/icons/delete.svg?react'
import AddIcon from '~/assets/icons/add.svg?react'

interface Props {
  project: Project
}

export function MemoryCard({ project }: Props) {
  const { t } = useT()
  const [items, setItems] = useState<MemoryItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingContent, setEditingContent] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [newContent, setNewContent] = useState('')
  const newInputRef = useRef<any>(null)

  const memoryOn = project.memory_enabled && !project.is_default

  const refresh = () => {
    if (!memoryOn) {
      setItems([])
      return
    }
    api
      .listMemoryItems(project.id)
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoaded(true))
  }
  useEffect(refresh, [project.id, memoryOn])

  const startEdit = (item: MemoryItem) => {
    setEditingId(item.id)
    setEditingContent(item.content)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditingContent('')
  }

  const saveEdit = async () => {
    if (!editingId) {
      cancelEdit()
      return
    }
    const trimmed = editingContent.trim()
    if (!trimmed) {
      // Clearing content = delete the memory item.
      await api.deleteMemoryItem(project.id, editingId)
    } else {
      await api.updateMemoryItem(project.id, editingId, trimmed)
    }
    setEditingId(null)
    refresh()
  }

  const deleteItem = async (id: string) => {
    await api.deleteMemoryItem(project.id, id)
    refresh()
  }

  const startCreate = () => {
    setIsCreating(true)
    setNewContent('')
    setTimeout(() => newInputRef.current?.focus(), 50)
  }

  const cancelCreate = () => {
    setIsCreating(false)
    setNewContent('')
  }

  const saveCreate = async () => {
    if (!newContent.trim()) {
      cancelCreate()
      return
    }
    await api.createMemoryItem(project.id, newContent.trim())
    setIsCreating(false)
    setNewContent('')
    refresh()
  }

  if (!memoryOn) {
    return (
      <WidgetCard
        title={t.widgets.memoryTitle}
        icon={<MemoryIcon className="h-5 w-5" />}
      >
        <div className="flex items-center justify-center text-xs text-msa-text-3 leading-relaxed">
          {t.widgets.memoryDisabled}
        </div>
      </WidgetCard>
    )
  }

  return (
    <WidgetCard
      title={t.widgets.memoryTitle}
      icon={<MemoryIcon className="h-5 w-5" />}
      count={items.length}
      className="flex-initial min-h-0 flex flex-col overflow-hidden"
      bodyClassName="flex-1 overflow-y-auto"
    >
      {!loaded ? (
        <DeferredSkeleton rows={6} className="py-1" />
      ) : items.length === 0 && !isCreating ? (
        <EmptyState
          size="sm"
          description={t.widgets.memoryEmpty}
          className="!py-2"
        />
      ) : (
        <div className="space-y-2.5">
          {items.map((item) =>
            editingId === item.id ? (
              <div key={item.id}>
                <Input.TextArea
                  value={editingContent}
                  onChange={(e) => setEditingContent(e.target.value)}
                  onBlur={cancelEdit}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault()
                      saveEdit()
                    }
                  }}
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  autoFocus
                  classNames={{ textarea: 'resize-none text-sm' }}
                />
              </div>
            ) : (
              <div
                key={item.id}
                className="group flex items-center gap-2 rounded-lg bg-msa-fill-2 px-3 py-3"
              >
                <p className="m-0 flex-1 line-clamp-2 text-sm leading-relaxed text-msa-text-2">
                  {item.content}
                </p>
                <Tooltip title={t.widgets.edit}>
                  <IconButton
                    icon={<EditIcon className="h-[18px] w-[18px]" />}
                    size="xs"
                    variant="ghost"
                    className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={() => startEdit(item)}
                  />
                </Tooltip>
                <Popconfirm
                  title={t.widgets.deleteMemory}
                  okText={t.workspace.delete}
                  cancelText={t.workspace.cancel}
                  onConfirm={() => deleteItem(item.id)}
                >
                  <Tooltip title={t.widgets.delete}>
                    <IconButton
                      icon={<DeleteIcon className="text-sm" />}
                      size="xs"
                      variant="ghost"
                      className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 hover:!text-msa-text-danger"
                    />
                  </Tooltip>
                </Popconfirm>
              </div>
            )
          )}

          {isCreating && (
            <div>
              <Input.TextArea
                ref={newInputRef}
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                onBlur={cancelCreate}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault()
                    saveCreate()
                  }
                }}
                autoSize={{ minRows: 2, maxRows: 6 }}
                autoFocus
                placeholder={t.widgets.addMemoryPlaceholder}
                classNames={{ textarea: 'resize-none text-sm' }}
              />
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex shrink-0 justify-center">
        <Button
          type="text"
          size="small"
          icon={<AddIcon />}
          onClick={startCreate}
          disabled={isCreating}
        >
          {t.widgets.addMemory}
        </Button>
      </div>
    </WidgetCard>
  )
}
