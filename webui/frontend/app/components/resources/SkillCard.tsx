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
  onRemove: () => void
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
        ? [{ key: 'view', label: t.resources.tryIt, onClick: onView }]
        : []),
      {
        key: 'remove',
        label: t.resources.remove,
        danger: true,
        onClick: () => setConfirmOpen(true)
      }
    ]
  }

  return (
    <div
      className="flex cursor-pointer flex-col gap-2 rounded-xl bg-msa-fill-2 p-4 transition-colors hover:bg-msa-fill-4"
      onClick={() => onToggle(!skill.enabled)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-msa-text-1">
          {skill.name}
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <MsaSwitch checked={skill.enabled} onChange={onToggle} />
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-msa-text-3">
          {oneLiner || t.resources.noDescription}
        </span>
        <Popconfirm
          title={t.resources.confirmRemoveSkill}
          open={confirmOpen}
          onConfirm={() => {
            setConfirmOpen(false)
            onRemove()
          }}
          onCancel={() => setConfirmOpen(false)}
          okText={t.resources.remove}
          okButtonProps={{ danger: true }}
        >
          <Dropdown menu={menu} trigger={['click']} placement="bottomRight">
            <Tooltip title={t.resources.more}>
              <Button
                size="small"
                type="text"
                icon={<MoreIcon className="h-4 w-4" />}
                className="!text-msa-text-3"
                onClick={(e) => e.stopPropagation()}
              />
            </Tooltip>
          </Dropdown>
        </Popconfirm>
      </div>
    </div>
  )
}
