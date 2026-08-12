import { Button, Drawer, Form, Input, Pagination } from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CardSkeletonGrid } from '~/components/common/CardSkeletonGrid'
import { EmptyState } from '~/components/common/EmptyState'
import { MsaSwitch } from '~/components/common/MsaSwitch'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Scope, Skill } from '~/lib/types'
import { SkillCard } from './SkillCard'
import { SkillDetailDrawer } from './SkillDetailDrawer'
import { SkillsFromLocalModal } from './SkillsFromLocalModal'

type EditingState = { mode: 'create' } | { mode: 'edit'; skill: Skill } | null
type ImportSource = 'local' | null

interface SkillsPanelProps {
  importing?: ImportSource
  onImportingChange?: (v: ImportSource) => void
}

export function SkillsPanel({
  importing: importingProp,
  onImportingChange
}: SkillsPanelProps) {
  const { t } = useT()
  const [searchParams] = useSearchParams()
  // Scope lives in the URL (?scope=), so it is derived, not mirrored in state.
  const activeScope: Scope =
    (searchParams.get('scope') as Scope | null) ?? 'global'
  const [items, setItems] = useState<Skill[] | null>(null)
  const [editing, setEditing] = useState<EditingState>(null)
  const [importingInternal, setImportingInternal] = useState<ImportSource>(null)
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null)
  const [page, setPage] = useState(1)

  const PAGE_SIZE = 12

  const importing = importingProp ?? importingInternal
  const setImporting = onImportingChange ?? setImportingInternal

  const refresh = () => api.listSkills(activeScope).then(setItems)
  useEffect(() => {
    setItems(null)
    setPage(1)
    refresh()
  }, [activeScope])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {items === null ? (
          <CardSkeletonGrid />
        ) : items.length === 0 ? (
          <EmptyState size="lg" description={t.resources.skillEmpty} />
        ) : (
          <>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {items
                .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                .map((s) => (
                  <SkillCard
                    key={s.id}
                    skill={s}
                    onToggle={async (v) => {
                      await api.updateSkill(s.id, { enabled: v })
                      refresh()
                    }}
                    onView={() => setDetailSkill(s)}
                    onRemove={async () => {
                      await api.deleteSkill(s.id)
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

      <SkillEditDrawer
        editing={editing}
        scope={activeScope}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null)
          refresh()
        }}
      />

      <SkillsFromLocalModal
        open={importing === 'local'}
        scope={activeScope}
        onClose={() => setImporting(null)}
        onImported={() => {
          setImporting(null)
          refresh()
        }}
      />

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

function SkillEditDrawer({
  editing,
  scope,
  onClose,
  onSaved
}: {
  editing: EditingState
  scope: Scope
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useT()
  const [form] = Form.useForm<{
    name: string
    kind: string
    content: string
    enabled: boolean
  }>()

  useEffect(() => {
    if (!editing) return
    if (editing.mode === 'edit') {
      form.setFieldsValue(editing.skill)
    } else {
      form.setFieldsValue({
        name: '',
        kind: 'file-type',
        content: '',
        enabled: true
      })
    }
  }, [editing, form])

  return (
    <Drawer
      open={!!editing}
      onClose={onClose}
      title={
        editing?.mode === 'edit' ? editing.skill.name : `+ ${t.resources.add}`
      }
      size={420}
      destroyOnHidden
      extra={
        <Button
          type="primary"
          onClick={async () => {
            const v = await form.validateFields()
            if (editing?.mode === 'edit') {
              await api.updateSkill(editing.skill.id, v)
            } else {
              await api.createSkill({ ...v, scope })
            }
            onSaved()
          }}
        >
          {t.resources.save}
        </Button>
      }
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          label={t.resources.name}
          name="name"
          rules={[{ required: true, max: 120 }]}
        >
          <Input />
        </Form.Item>
        <Form.Item label={t.resources.kind} name="kind">
          <Input />
        </Form.Item>
        <Form.Item label="content" name="content">
          <Input.TextArea
            rows={6}
            classNames={{ textarea: 'resize-none font-mono text-xs' }}
          />
        </Form.Item>
        <Form.Item
          label={t.resources.enabled}
          name="enabled"
          valuePropName="checked"
        >
          <MsaSwitch />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
