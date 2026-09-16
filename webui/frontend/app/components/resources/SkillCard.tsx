import { Button, Dropdown, Popconfirm } from 'antd'
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
        ? [{ key: 'view', label: t.resources.tryIt, onClick: onView }]
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
        {/* The whole card toggles the skill, so the action area has to swallow
            its clicks — INCLUDING the confirm popup's. That popup renders in a
            portal but is a React child of Popconfirm, and React events bubble
            along the component tree, not the DOM one: confirming "remove" also
            ran the card's onToggle, firing a DELETE and a PATCH at the same
            skill. Whichever the server finished second answered 404 ("Skill not
            found") for an operation that had actually succeeded. */}
        <span onClick={(e) => e.stopPropagation()}>
          <Popconfirm
            title={
              skill.origin === 'legacy-path'
                ? t.resources.confirmRemoveLegacySkill
                : t.resources.confirmRemoveSkill
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
            {/* More menu — hover-triggered, so it carries no tooltip (that would
                overlap the menu); the i18n label moves to `aria-label`. */}
            <Dropdown menu={menu} trigger={['hover']} placement="bottomRight">
              <Button
                aria-label={t.resources.more}
                size="small"
                type="text"
                icon={<MoreIcon className="h-5 w-5" />}
                className="!text-msa-text-3"
              />
            </Dropdown>
          </Popconfirm>
        </span>
      </div>
    </div>
  )
}
