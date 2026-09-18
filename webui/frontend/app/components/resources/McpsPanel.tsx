import { App, Pagination } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
import { useOnMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import { useMcpHealth } from '~/lib/mcpHealth'
import type { Mcp, Scope } from '~/lib/types'
import { McpCard } from './McpCard'
import { McpCustomModal } from './McpCustomModal'
import { McpJsonModal } from './McpJsonModal'

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

  // Reachability, by mcp id. Resolved alongside the list so a stale endpoint is
  // visible without the user having to test each card by hand — that manual
  // probe is still there, it just is not the only way to find out any more.
  // Shared with the project tab and the composer pill through `useMcpHealth`,
  // which serves the last sweep from memory: coming back to this page used to
  // re-probe every server (seconds, with all the cards spinning) even though
  // the answer was already known. Stale-while-revalidate is part of that
  // contract — known verdicts stay on screen while a sweep re-runs, so only
  // cards with no verdict yet spin, gated by `sweeping`.
  const {
    rows: health,
    sweeping,
    refresh: refreshHealth,
    put: putHealth
  } = useMcpHealth()

  // A JUST-ADDED stdio server gets one deep check (real spawn+initialize):
  // the sweep's existence-only probe would light it green while the package
  // is broken or still cold-installing — observed with a server that crashes
  // against a newer mcp SDK and looked fine until a chat needed it.
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

  // `[]` on failure, never left at `null`: `null` is this list's "still
  // loading" and would hold the skeleton up forever (health already settles
  // that way just below the list request).
  // `fresh` = a mutation just changed which servers exist or are enabled, so
  // the cached sweep describes the wrong set and has to be re-run. A plain
  // mount (or a scope switch) is happy with the cached one.
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
  useEffect(() => {
    setItems(null)
    setPage(1)
    knownIdsRef.current = null // new scope = new baseline, not "all new"
    refresh()
  }, [activeScope])

  // Refresh when the set changes elsewhere (e.g. an external API call relayed by
  // the server-event bridge). `fresh` re-runs the health sweep.
  useOnMcpSkillChanged(() => refresh(true))

  const scopeBadge =
    activeScope === 'global'
      ? t.mcpImport.hubGlobalBadge
      : t.mcpImport.hubProjectBadge

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {items === null ? (
          <CardSkeletonGrid />
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
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
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
                      refresh(true)
                    }}
                    onReconnect={async () => {
                      try {
                        const result = await api.checkMcpHealth(m.id)
                        putHealth(result)
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
                      refresh(true)
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

      <McpJsonModal
        open={viaJson}
        scope={activeScope}
        scopeBadge={scopeBadge}
        items={items ?? []}
        onSaved={() => refresh(true)}
        onClose={() => onViaJsonChange?.(false)}
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
          refresh(true)
        }}
      />
    </div>
  )
}
