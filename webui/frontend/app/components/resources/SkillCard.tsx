import { Button, Dropdown, Popconfirm, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useMemo, useState } from 'react'
import { MsaSwitch } from '~/components/common/MsaSwitch'
import { useT } from '~/lib/i18n'
import type { Skill } from '~/lib/types'
import MoreIcon from '~/assets/icons/more.svg?react'

interface SkillCardProps {
  skill: Skill
  onToggle: (v: boolean) => void
  onView?: () => void
  onRemove?: () => void
}

export function SkillCard({
  skill,
  onToggle,
  onView,
  onRemove
}: SkillCardProps) {
  const { t } = useT()
  const [confirmOpen, setConfirmOpen] = useState(false)

  const oneLiner = useMemo(() => {
    const firstLine = (skill.content || '')
      .split('\n')
      .map((s) => s.trim())
      .find((s) => s && !s.startsWith('#'))
    return firstLine || ''
  }, [skill.content])

  const menu: MenuProps = {
    onClick: (e) => e.domEvent.stopPropagation(),
    items: [
      ...(onView
        ? [{ key: 'view', label: t.skillDetail.title, onClick: onView }]
        : []),
      ...(onRemove
        ? [
            {
              key: 'remove',
              label: t.resources.remove,
              danger: true,
              onClick: () => setConfirmOpen(true)
            }
          ]
        : [])
    ]
  }

  return (
    <div
      className="flex cursor-pointer flex-col gap-2 rounded-xl bg-msa-fill-2 p-4 transition-colors hover:bg-msa-fill-4"
      onClick={onView}
      role="button"
      tabIndex={0}
      aria-label={skill.name}
      onKeyDown={(e) => {
        if (
          e.target === e.currentTarget &&
          (e.key === 'Enter' || e.key === ' ')
        ) {
          e.preventDefault()
          onView?.()
        }
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-msa-text-1">
          {skill.name}
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <MsaSwitch
            checked={skill.enabled}
            onChange={onToggle}
            ariaLabel={skill.name}
          />
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-msa-text-3">
          {oneLiner || t.resources.noDescription}
        </span>
        {/* Portal clicks bubble through React; menu/confirmation actions must
            not also open the card's detail drawer. */}
        <span onClick={(e) => e.stopPropagation()}>
          <Popconfirm
            title={
              (skill.origin === 'legacy-path'
                ? t.resources.confirmRemoveLegacySkill
                : t.resources.confirmRemoveSkill) + ` ${skill.name}`
            }
            open={confirmOpen}
            onConfirm={() => {
              setConfirmOpen(false)
              onRemove?.()
            }}
            onCancel={() => setConfirmOpen(false)}
            okText={t.resources.remove}
            okButtonProps={{ danger: true }}
          >
            <Dropdown menu={menu} trigger={['click']} placement="bottomRight">
              <Tooltip title={t.resources.more}>
                <Button
                  aria-label={t.resources.more}
                  size="small"
                  type="text"
                  icon={<MoreIcon className="h-5 w-5" />}
                  className="!text-msa-text-3"
                />
              </Tooltip>
            </Dropdown>
          </Popconfirm>
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="text-msa-text-3">
          {skill.installation?.source.provider === 'github'
            ? 'GitHub'
            : skill.installation?.source.provider === 'modelscope'
              ? 'ModelScope'
              : ''}
        </span>
        <span className="text-msa-text-2">
          {skill.update?.remote_status === 'available'
            ? t.skillManagement.available
            : skill.update?.remote_status === 'failed'
              ? t.skillManagement.checkFailed
              : ''}
          {skill.update?.local_status === 'modified'
            ? `${skill.update?.remote_status === 'available' ? ' · ' : ''}${t.skillManagement.modified}`
            : ''}
        </span>
      </div>
    </div>
  )
}
