import { Dropdown, Segmented } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import AddIcon from '~/assets/icons/add.svg?react'
import { MsaButton } from '~/components/common/MsaButton'
import {
  SkillCollection,
  type SkillImportSource
} from '~/components/resources/SkillCollection'
import { useT } from '~/lib/i18n'
import type { Project, Scope } from '~/lib/types'

export function SkillTabPanel({ project }: { project: Project }) {
  const { t } = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const [importing, setImporting] = useState<SkillImportSource>(null)
  const projectScope: Scope = `project:${project.id}`
  const scope: Scope =
    searchParams.get('scope') === 'project' ? projectScope : 'global'
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <Segmented<Scope>
          value={scope}
          options={[
            { value: 'global', label: t.resources.globalSkills },
            { value: projectScope, label: t.resources.projectSkills }
          ]}
          onChange={(value) =>
            setSearchParams(
              (previous) => {
                const next = new URLSearchParams(previous)
                next.set('scope', value === 'global' ? 'global' : 'project')
                return next
              },
              { replace: true }
            )
          }
        />
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              {
                key: 'link',
                label: t.skillManagement.fromLink,
                onClick: () => setImporting('link')
              },
              {
                key: 'local',
                label: t.skillManagement.fromLocal,
                onClick: () => setImporting('local')
              }
            ]
          }}
        >
          <MsaButton
            variant="primary"
            className="rounded-[12px] text-[13px]"
            icon={<AddIcon className="h-5 w-5" />}
          >
            {t.resources.addSkill}
          </MsaButton>
        </Dropdown>
      </div>
      <SkillCollection
        key={scope}
        scope={scope}
        importing={importing}
        onImportingChange={setImporting}
      />
    </div>
  )
}
