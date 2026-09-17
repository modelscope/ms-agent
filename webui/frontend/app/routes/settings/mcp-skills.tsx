import { Tabs } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import './mcp-skills.css'
import McpIcon from '~/assets/icons/mcp.svg?react'
import SkillIcon from '~/assets/icons/skill.svg?react'
import { MsaButton } from '~/components/common/MsaButton'
import { McpsPanel } from '~/components/resources/McpsPanel'
import { SkillsPanel } from '~/components/resources/SkillsPanel'
import { useT } from '~/lib/i18n'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/mcp-skills'
import AddIcon from '~/assets/icons/add.svg?react'

type McpImportSource = 'custom' | null
type SkillImportSource = 'local' | null

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.navMcpSkills, t.settings.title) }]
}

export default function SettingsMcpSkills() {
  const { t } = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = (searchParams.get('tab') as 'mcps' | 'skills' | null) ?? 'mcps'

  // Lifted state for panel toolbars
  const [viaJson, setViaJson] = useState(false)
  const [mcpImporting, setMcpImporting] = useState<McpImportSource>(null)
  const [skillImporting, setSkillImporting] = useState<SkillImportSource>(null)

  const onTabChange = (next: string) => {
    const sp = new URLSearchParams(searchParams)
    sp.set('tab', next)
    sp.delete('scope')
    setSearchParams(sp, { replace: true })
  }

  const actions =
    tab === 'mcps' ? (
      <>
        {/* Both open something on top of the list now (a dialog each), so neither
            has to know about the other: no disabled state, no active highlight. */}
        <MsaButton
          key="via-json"
          variant="tonal"
          className="rounded-[12px] text-[13px]"
          onClick={() => setViaJson(true)}
        >
          {t.resources.viaJson}
        </MsaButton>
        <MsaButton
          key="add-mcp"
          variant="primary"
          className="rounded-[12px] text-[13px]"
          icon={<AddIcon className="h-5 w-5" />}
          onClick={() => setMcpImporting('custom')}
        >
          {t.resources.addMcp}
        </MsaButton>
      </>
    ) : (
      <MsaButton
        variant="primary"
        key="add-skill"
        className="rounded-[12px] text-[13px]"
        icon={<AddIcon className="h-5 w-5" />}
        onClick={() => setSkillImporting('local')}
      >
        {t.resources.addSkill}
      </MsaButton>
    )

  // Desktop / wide enough: the action buttons sit on the tab bar's extra slot
  // (right side). When the content area is too narrow for the tabs + buttons to
  // share one row (which would squeeze the tab labels off-screen and break
  // antd's nav overflow measurement), they drop to a standalone row above the
  // tabs instead. The switch is driven by a container query on the actual
  // content width (see mcp-skills.css), not a fixed viewport breakpoint.
  const extra = (
    <div className="mcp-skills-extra items-center gap-3">{actions}</div>
  )

  return (
    <div className="mcp-skills-shell flex h-full min-h-0 flex-col">
      <div className="mcp-skills-top-actions mb-3 items-center gap-3">
        {actions}
      </div>
      <Tabs
        activeKey={tab}
        onChange={onTabChange}
        indicator={{ size: 8, align: 'center' }}
        className="flex min-h-0 flex-1 flex-col mcp-skills-tabs-flex"
        classNames={{
          indicator: 'bg-msa-text-1 h-[2px]',
          header: 'before:hidden',
          body: 'h-full'
        }}
        tabBarExtraContent={extra}
        items={[
          {
            key: 'mcps',
            label: (
              <span
                className={`flex items-center gap-1.5 ${
                  tab === 'mcps' ? 'font-semibold' : ''
                }`}
              >
                {tab === 'mcps' && <McpIcon className="h-5 w-5" />}
                {t.settings.mcpsTab}
              </span>
            ),
            children: (
              <McpsPanel
                viaJson={viaJson}
                onViaJsonChange={setViaJson}
                importing={mcpImporting}
                onImportingChange={setMcpImporting}
              />
            )
          },
          {
            key: 'skills',
            label: (
              <span
                className={`flex items-center gap-1.5 ${
                  tab === 'skills' ? 'font-semibold' : ''
                }`}
              >
                {tab === 'skills' && <SkillIcon className="h-5 w-5" />}
                {t.settings.skillsTab}
              </span>
            ),
            children: (
              <SkillsPanel
                importing={skillImporting}
                onImportingChange={setSkillImporting}
              />
            )
          }
        ]}
      />
    </div>
  )
}
