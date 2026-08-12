import { App, Pagination } from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Mcp, Scope } from '~/lib/types'
import { McpCard } from './McpCard'
import { McpCustomModal } from './McpCustomModal'
import { McpJsonView } from './McpJsonView'

type ImportSource = 'custom' | null

interface McpsPanelProps {
  viaJson?: boolean
  onViaJsonChange?: (v: boolean) => void
  importing?: ImportSource
  onImportingChange?: (v: ImportSource) => void
}

export function McpsPanel({
  viaJson = false,
  onViaJsonChange,
  importing: importingProp,
  onImportingChange
}: McpsPanelProps) {
  const { t } = useT()
  const { message } = App.useApp()
  const [searchParams] = useSearchParams()
  // Scope lives in the URL (?scope=), so it is derived, not mirrored in state.
  const activeScope: Scope =
    (searchParams.get('scope') as Scope | null) ?? 'global'
  const [items, setItems] = useState<Mcp[] | null>(null)
  const [editingMcp, setEditingMcp] = useState<Mcp | null>(null)
  const [importingInternal, setImportingInternal] = useState<ImportSource>(null)
  const [page, setPage] = useState(1)

  const PAGE_SIZE = 12

  const importing = importingProp ?? importingInternal
  const setImporting = onImportingChange ?? setImportingInternal

  const refresh = () => api.listMcps(activeScope).then(setItems)
  useEffect(() => {
    setItems(null)
    setPage(1)
    refresh()
  }, [activeScope])

  const scopeBadge =
    activeScope === 'global'
      ? t.mcpImport.hubGlobalBadge
      : t.mcpImport.hubProjectBadge

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {viaJson ? (
          <McpJsonView
            scope={activeScope}
            items={items ?? []}
            onSaved={refresh}
            onCancel={() => onViaJsonChange?.(false)}
          />
        ) : items === null ? (
          <CardSkeletonGrid />
        ) : items.length === 0 ? (
          <EmptyState size="lg" description={t.resources.mcpEmpty} />
        ) : (
          <>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {items
                .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                .map((m) => (
                  <McpCard
                    key={m.id}
                    mcp={m}
                    onToggle={async (v) => {
                      await api.updateMcp(m.id, { enabled: v })
                      refresh()
                    }}
                    onReconnect={async () => {
                      try {
                        const result = await api.checkMcpHealth(m.id)
                        if (result.healthy) {
                          message.success(`${m.name}: ${t.resources.statusOk}`)
                        } else {
                          message.error(`${m.name}: ${result.error || t.resources.statusError}`)
                        }
                      } catch {
                        message.error(`${m.name}: ${t.resources.statusError}`)
                      }
                    }}
                    onEdit={() => setEditingMcp(m)}
                    onRemove={async () => {
                      await api.deleteMcp(m.id)
                      refresh()
                    }}
                  />
                ))}
            </div>
            {items.length > PAGE_SIZE && (
              <div className="mt-4 flex justify-end">
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

      <McpCustomModal
        open={importing === 'custom' || !!editingMcp}
        scope={activeScope}
        editingMcp={editingMcp}
        scopeBadge={scopeBadge}
        onClose={() => {
          setImporting(null)
          setEditingMcp(null)
        }}
        onSaved={() => {
          setImporting(null)
          setEditingMcp(null)
          refresh()
        }}
      />
    </div>
  )
}
