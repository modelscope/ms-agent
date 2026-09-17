import { Pagination, Segmented } from 'antd'
import { App } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import { useMcpHealth } from '~/lib/mcpHealth'
import type { Mcp, Project, Scope } from '~/lib/types'
import { McpCard } from '~/components/resources/McpCard'
import { McpCustomModal } from '~/components/resources/McpCustomModal'
import { McpJsonModal } from '~/components/resources/McpJsonModal'
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

  // Reachability, same contract as McpsPanel: the verdicts come from the shared
  // `useMcpHealth` cache (this tab and the composer pill mount together, and
  // used to sweep once each), stale-while-revalidate so known verdicts stay
  // during a sweep, plus one DEEP check for a just-added stdio server, whose
  // existence-only sweep verdict would lie green.
  const {
    rows: health,
    sweeping,
    refresh: refreshHealth,
    put: putHealth
  } = useMcpHealth()
  const [deepChecking, setDeepChecking] = useState<Set<string>>(new Set())
  const knownIdsRef = useRef<Set<string> | null>(null)
  const deepCheck = (id: string) => {
    setDeepChecking((prev) => new Set(prev).add(id))
    api
      .checkMcpHealth(id)
      .then(putHealth)
      .catch(() => {})
      .finally(() =>
        setDeepChecking((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      )
  }

  // `fresh` = a mutation just changed the server set, so the cached sweep is
  // about the wrong one; a plain mount or scope switch reuses it.
  const refresh = (fresh = false) =>
    api
      .listMcps(activeScope)
      .then((rows) => {
        setItems(rows)
        const known = knownIdsRef.current
        knownIdsRef.current = new Set(rows.map((r) => r.id))
        void refreshHealth(fresh)
        if (known)
          rows
            .filter(
              (r) => r.enabled && r.transport === 'stdio' && !known.has(r.id)
            )
            .forEach((r) => deepCheck(r.id))
      })
      .catch(() => setItems([]))

  const refreshAndNotify = () => {
    refresh(true)
    dispatchMcpSkillChanged()
  }
  useEffect(() => {
    refresh()
    setPage(1)
  }, [activeScope])

  // Reset state when project changes (the scope itself is URL-driven; a
  // cross-project navigation carries no ?scope, which already means global).
  // Closing the JSON dialog matters: its document belongs to the scope it was
  // opened for, and saving it replaces every server in that scope.
  useEffect(() => {
    setViaJson(false)
    setPage(1)
  }, [project.id])

  const scopeOptions: { value: Scope; label: string }[] = [
    { value: 'global', label: t.resources.globalMcps },
    { value: projectScope, label: t.resources.projectMcps }
  ]

  // Both dialogs write into the selected scope, and both say so in their title.
  const scopeBadge =
    activeScope === 'global'
      ? t.mcpImport.hubGlobalBadge
      : t.mcpImport.hubProjectBadge

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <Segmented<Scope>
          className="text-[13px]"
          value={activeScope}
          onChange={setActiveScope}
          options={scopeOptions}
        />
        <div className="flex items-center gap-3">
          <MsaButton
            variant="tonal"
            className="rounded-[12px] text-[13px]"
            onClick={() => setViaJson(true)}
          >
            {t.resources.viaJson}
          </MsaButton>
          <MsaButton
            variant="primary"
            className="rounded-[12px] text-[13px]"
            icon={<AddIcon className="h-5 w-5" />}
            onClick={() => setImporting('custom')}
          >
            {t.resources.addMcp}
          </MsaButton>
        </div>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto overflow-x-hidden">
        {items === null ? (
          <CardSkeletonGrid className="grid grid-cols-1 gap-3 md:grid-cols-2" />
        ) : items.length === 0 ? (
          <EmptyState
            size="lg"
            description={`${t.resources.mcpEmpty}${t.resources.mcpEmptyHint}`}
            action={
              <EmptyStateAction onClick={() => setImporting('custom')}>
                {t.resources.addNow}
              </EmptyStateAction>
            }
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {items
                .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                .map((m) => (
                  <McpCard
                    key={m.id}
                    mcp={m}
                    probing={
                      (sweeping && !health[m.id]) || deepChecking.has(m.id)
                    }
                    healthy={
                      deepChecking.has(m.id)
                        ? undefined // the shallow verdict must not flash green
                        : health[m.id]?.healthy
                    }
                    healthError={
                      deepChecking.has(m.id) ? undefined : health[m.id]?.error
                    }
                    onToggle={async (v) => {
                      await api.updateMcp(m.id, { enabled: v })
                      refreshAndNotify()
                    }}
                    onReconnect={async () => {
                      try {
                        const result = await api.checkMcpHealth(m.id)
                        putHealth(result)
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
      <McpJsonModal
        open={viaJson}
        scope={activeScope}
        scopeBadge={scopeBadge}
        items={items ?? []}
        onSaved={refreshAndNotify}
        onClose={() => setViaJson(false)}
      />

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
          refreshAndNotify()
        }}
      />
    </div>
  )
}
