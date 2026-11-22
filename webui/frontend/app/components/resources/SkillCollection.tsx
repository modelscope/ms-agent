import {
  App,
  Button,
  Checkbox,
  Dropdown,
  Pagination,
  Segmented,
  Tooltip
} from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import MoreIcon from '~/assets/icons/more.svg?react'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged, useOnMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import {
  isCancelled,
  skillErrorText,
  useSkillOperation
} from '~/lib/skillManagement'
import type { Scope, Skill } from '~/lib/types'
import { SkillCard } from './SkillCard'
import { SkillDetailDrawer } from './SkillDetailDrawer'
import { SkillsFromLinkModal } from './SkillsFromLinkModal'
import { SkillsFromLocalModal } from './SkillsFromLocalModal'

export type SkillImportSource = 'local' | 'link' | null

export function SkillCollection({
  scope,
  importing,
  onImportingChange
}: {
  scope: Scope
  importing: SkillImportSource
  onImportingChange: (value: SkillImportSource) => void
}) {
  const { t } = useT()
  const s = t.skillManagement
  const { message } = App.useApp()
  const operation = useSkillOperation()
  const [items, setItems] = useState<Skill[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [checking, setChecking] = useState(false)
  const [autoCheck, setAutoCheck] = useState(true)
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const sequence = useRef(0)
  const pageSize = 12

  const refresh = useCallback(async () => {
    const seq = ++sequence.current
    setRefreshing(true)
    try {
      const rows = await api.listSkills(scope, { silent: true })
      if (seq === sequence.current) {
        setItems(rows)
        setLoadFailed(false)
      }
    } catch {
      // Keep the last successful snapshot. A failed request is not an empty
      // library, and the inline retry also works before the first load.
      if (seq === sequence.current) setLoadFailed(true)
    } finally {
      if (seq === sequence.current) setRefreshing(false)
    }
  }, [scope])

  useEffect(() => {
    setItems(null)
    setPage(1)
    setSelected(null)
    setFilter('all')
    setError('')
    setLoadFailed(false)
    refresh()
    return () => {
      sequence.current++
    }
  }, [refresh])
  useOnMcpSkillChanged(refresh)

  async function check(force: boolean) {
    if (checking) return
    setChecking(true)
    if (force) setError('')
    try {
      const result = (await operation.run(() =>
        api.checkSkillUpdates(scope, force)
      )) as { remote_status: string }[]
      await refresh()
      if (
        force &&
        result.every(
          (r) => r.remote_status !== 'available' && r.remote_status !== 'failed'
        )
      )
        message.info(s.none)
    } catch (e) {
      if (force && !isCancelled(e)) setError(skillErrorText(e, s))
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    let disposed = false
    api
      .skillManagementSettings()
      .then((settings) => {
        if (disposed) return
        setAutoCheck(settings.auto_check)
      })
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [scope])

  const updates =
    items?.filter((item) => item.update?.remote_status === 'available')
      .length ?? 0
  const shown =
    items?.filter(
      (item) => filter === 'all' || item.update?.remote_status === 'available'
    ) ?? []
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(shown.length / pageSize))
  )
  const detail = items?.find((item) => item.id === selected) ?? null
  const changed = dispatchMcpSkillChanged
  const imported = () => {
    onImportingChange(null)
    setFilter('all')
    setPage(1)
    changed()
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <Segmented
          value={filter}
          onChange={(value) => {
            setFilter(value)
            setPage(1)
          }}
          options={[
            { value: 'all', label: s.all },
            ...(updates || filter === 'updates'
              ? [{ value: 'updates', label: `${s.updates} ${updates}` }]
              : [])
          ]}
        />
        <div className="flex items-center gap-2">
          <Button
            loading={checking}
            onClick={() => check(true)}
            disabled={!items?.some((item) => item.capabilities?.can_check)}
          >
            {s.check}
          </Button>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                {
                  key: 'auto',
                  label: (
                    <Checkbox
                      checked={autoCheck}
                      onChange={async (e) => {
                        const value = e.target.checked
                        try {
                          await api.setSkillManagementSettings(value)
                          setAutoCheck(value)
                        } catch {
                          /* global API feedback */
                        }
                      }}
                    >
                      {s.autoCheck}
                    </Checkbox>
                  )
                }
              ]
            }}
          >
            <Tooltip title={t.resources.more}>
              <Button
                type="text"
                aria-label={t.resources.more}
                icon={<MoreIcon className="h-5 w-5" />}
              />
            </Tooltip>
          </Dropdown>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-sm text-msa-deco-red">
          {error}
        </p>
      )}
      {loadFailed && (
        <div
          role="alert"
          className="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-lg bg-msa-fill-2 px-4 py-3 text-sm text-msa-text-2"
        >
          <span>{s.listFailed}</span>
          <Button size="small" loading={refreshing} onClick={refresh}>
            {s.retry}
          </Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto" aria-busy={refreshing}>
        {items === null ? (
          loadFailed ? null : (
            <CardSkeletonGrid />
          )
        ) : items.length === 0 ? (
          loadFailed ? null : (
            <EmptyState
              size="lg"
              description={`${t.resources.skillEmpty}${t.resources.skillEmptyHint}`}
              action={
                <EmptyStateAction onClick={() => onImportingChange('link')}>
                  {t.resources.addNow}
                </EmptyStateAction>
              }
            />
          )
        ) : shown.length === 0 ? (
          <EmptyState description={s.none} />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown
                .slice((currentPage - 1) * pageSize, currentPage * pageSize)
                .map((skill) => (
                  <SkillCard
                    key={skill.id}
                    skill={skill}
                    onView={() => setSelected(skill.id)}
                    onToggle={async (enabled) => {
                      await api.updateSkill(skill.id, { enabled })
                      changed()
                    }}
                    onRemove={
                      skill.removable
                        ? async () => {
                            await api.deleteSkill(skill.id)
                            changed()
                          }
                        : undefined
                    }
                  />
                ))}
            </div>
            {shown.length > pageSize && (
              <div className="mt-4 flex justify-end">
                <Pagination
                  current={currentPage}
                  pageSize={pageSize}
                  total={shown.length}
                  onChange={setPage}
                  size="small"
                />
              </div>
            )}
          </>
        )}
      </div>
      <SkillsFromLinkModal
        open={importing === 'link'}
        scope={scope}
        onClose={() => onImportingChange(null)}
        onImported={imported}
      />
      <SkillsFromLocalModal
        open={importing === 'local'}
        scope={scope}
        onClose={() => onImportingChange(null)}
        onImported={imported}
      />
      <SkillDetailDrawer
        open={!!detail}
        skill={detail}
        allSkills={items ?? []}
        onClose={() => setSelected(null)}
        onSkillChange={(skill) => setSelected(skill.id)}
      />
    </div>
  )
}
