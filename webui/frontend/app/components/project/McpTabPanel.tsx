import { Pagination, Segmented } from 'antd'
import { App } from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState } from '~/components/common/EmptyState'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { Mcp, Project, Scope } from '~/lib/types'
import { McpCard } from '~/components/resources/McpCard'
import { McpCustomModal } from '~/components/resources/McpCustomModal'
import { McpJsonView } from '~/components/resources/McpJsonView'
import AddIcon from '~/assets/icons/add.svg?react'

// ---------- Main component ----------

interface Props {
  project: Project
}

type ImportSource = 'custom' | null

export function McpTabPanel({ project }: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const projectScope: Scope = `project:${project.id}`
  // Scope lives in the URL (?scope=global|project, next to ?tab=) so a reload
  // lands back on the same sub-view. Shared with the Skills tab by design.
  const [searchParams, setSearchParams] = useSearchParams()
  const activeScope: Scope =
    searchParams.get('scope') === 'project' ? projectScope : 'global'
  const setActiveScope = (v: Scope) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('scope', v === 'global' ? 'global' : 'project')
        return next
      },
      { replace: true }
    )
  const [items, setItems] = useState<Mcp[] | null>(null)
  const [importing, setImporting] = useState<ImportSource>(null)
  const [editingMcp, setEditingMcp] = useState<Mcp | null>(null)
  const [viaJson, setViaJson] = useState(false)
  const [page, setPage] = useState(1)

  const PAGE_SIZE = 10

  const refresh = () =>
    api
      .listMcps(activeScope)
      .then(setItems)
      .catch(() => setItems([]))

  const refreshAndNotify = () => {
    refresh()
    dispatchMcpSkillChanged()
  }
  useEffect(() => {
    refresh()
    setPage(1)
  }, [activeScope])

  // Reset state when project changes (the scope itself is URL-driven; a
  // cross-project navigation carries no ?scope, which already means global).
  useEffect(() => {
    setViaJson(false)
    setPage(1)
  }, [project.id])

  const scopeOptions: { value: Scope; label: string }[] = [
    { value: 'global', label: t.resources.globalMcps },
    { value: projectScope, label: t.resources.projectMcps }
  ]

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <Segmented<Scope>
          value={activeScope}
          onChange={setActiveScope}
          options={scopeOptions}
        />
        <div className="flex items-center gap-3">
          <MsaButton
            variant="tonal"
            onClick={() => setViaJson(true)}
            className={viaJson ? '!text-msa-text-brand1' : ''}
          >
            {t.resources.viaJson}
          </MsaButton>
          <MsaButton
            variant="primary"
            icon={<AddIcon className="h-4 w-4" />}
            disabled={viaJson}
            onClick={() => setImporting('custom')}
          >
            {t.resources.addMcp}
          </MsaButton>
        </div>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto overflow-x-hidden">
        {viaJson ? (
          <McpJsonView
            scope={activeScope}
            items={items ?? []}
            onSaved={refreshAndNotify}
            onCancel={() => setViaJson(false)}
          />
        ) : items === null ? (
          <CardSkeletonGrid className="grid grid-cols-1 gap-3 md:grid-cols-2" />
        ) : items.length === 0 ? (
          <EmptyState size="lg" description={t.resources.mcpEmpty} />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {items
                .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                .map((m) => (
                  <McpCard
                    key={m.id}
                    mcp={m}
                    onToggle={async (v) => {
                      await api.updateMcp(m.id, { enabled: v })
                      refreshAndNotify()
                    }}
                    onReconnect={async () => {
                      try {
                        const result = await api.checkMcpHealth(m.id)
                        if (result.healthy) {
                          message.success(`${m.name}: ${t.resources.statusOk}`)
                        } else {
                          message.error(
                            `${m.name}: ${result.error || t.resources.statusError}`
                          )
                        }
                      } catch {
                        message.error(`${m.name}: ${t.resources.statusError}`)
                      }
                    }}
                    onEdit={() => setEditingMcp(m)}
                    onRemove={async () => {
                      await api.deleteMcp(m.id)
                      refreshAndNotify()
                    }}
                  />
                ))}
            </div>
            {items.length > PAGE_SIZE && (
              <div className="mt-3 flex justify-end">
                <Pagination
                  current={page}
                  pageSize={PAGE_SIZE}
                  total={items.length}
                  onChange={setPage}
                  size="small"
                />
              </div>
            )}
          </>
        )}
      </div>

      {/* Modals */}
      <McpCustomModal
        open={importing === 'custom' || !!editingMcp}
        scope={activeScope}
        editingMcp={editingMcp}
        scopeBadge={
          activeScope === 'global'
            ? t.mcpImport.hubGlobalBadge
            : t.mcpImport.hubProjectBadge
        }
        onClose={() => {
          setImporting(null)
          setEditingMcp(null)
        }}
        onSaved={() => {
          setImporting(null)
          setEditingMcp(null)
          refreshAndNotify()
        }}
      />
    </div>
  )
}
