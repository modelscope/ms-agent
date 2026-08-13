import { Pagination, Segmented } from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState } from '~/components/common/EmptyState'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { Project, Scope, Skill } from '~/lib/types'
import { SkillCard } from '~/components/resources/SkillCard'
import { SkillsFromLocalModal } from '~/components/resources/SkillsFromLocalModal'
import { SkillDetailDrawer } from '~/components/resources/SkillDetailDrawer'
import AddIcon from '~/assets/icons/add.svg?react'

// ---------- Main component ----------

interface Props {
  project: Project
}

export function SkillTabPanel({ project }: Props) {
  const { t } = useT()
  const projectScope: Scope = `project:${project.id}`
  // Scope lives in the URL (?scope=global|project, next to ?tab=) so a reload
  // lands back on the same sub-view. Shared with the MCPs tab by design.
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
  const [items, setItems] = useState<Skill[] | null>(null)
  const [showLocal, setShowLocal] = useState(false)
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null)
  const [page, setPage] = useState(1)

  const PAGE_SIZE = 10

  const refresh = () =>
    api
      .listSkills(activeScope)
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

  // Reset state when project changes (the scope itself is URL-driven).
  useEffect(() => {
    setPage(1)
  }, [project.id])

  const scopeOptions: { value: Scope; label: string }[] = [
    { value: 'global', label: t.resources.globalSkills },
    { value: projectScope, label: t.resources.projectSkills }
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
        <MsaButton
          variant="primary"
          icon={<AddIcon className="h-4 w-4" />}
          onClick={() => setShowLocal(true)}
        >
          {t.resources.addSkill}
        </MsaButton>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {items === null ? (
          <CardSkeletonGrid className="grid grid-cols-1 gap-3 md:grid-cols-2" />
        ) : items.length === 0 ? (
          <EmptyState size="lg" description={t.resources.skillEmpty} />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {items
                .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                .map((s) => (
                  <SkillCard
                    key={s.id}
                    skill={s}
                    onToggle={async (v) => {
                      await api.updateSkill(s.id, { enabled: v })
                      refreshAndNotify()
                    }}
                    onView={() => setDetailSkill(s)}
                    onRemove={async () => {
                      await api.deleteSkill(s.id)
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

      {/* Upload modal */}
      <SkillsFromLocalModal
        open={showLocal}
        scope={activeScope}
        onClose={() => setShowLocal(false)}
        onImported={() => {
          setShowLocal(false)
          refreshAndNotify()
        }}
      />

      {/* Detail drawer */}
      <SkillDetailDrawer
        open={!!detailSkill}
        skill={detailSkill}
        allSkills={items ?? []}
        onClose={() => setDetailSkill(null)}
        onSkillChange={setDetailSkill}
      />
    </div>
  )
}
