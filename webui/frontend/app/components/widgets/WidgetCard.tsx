import { Card, Tooltip } from 'antd'
import { IconButton } from '~/components/common/IconButton'
import { useT } from '~/lib/i18n'
import EditIcon from '~/assets/icons/edit.svg?react'

interface Props {
  title: string
  icon?: React.ReactNode
  count?: number
  /** Small tag after the title/count — e.g. which memory storage backend the
   * project uses, so the two very different memory UIs are self-explaining. */
  badge?: string
  onEdit?: () => void
  extra?: React.ReactNode
  className?: string
  bodyClassName?: string
  children: React.ReactNode
}

export function WidgetCard({
  title,
  icon,
  count,
  badge,
  onEdit,
  extra,
  className,
  bodyClassName,
  children
}: Props) {
  const { t } = useT()
  return (
    <Card
      className={`!border-msa-line-1 !rounded-xl ${className ?? ''}`}
      classNames={{
        title: 'flex-shrink-0 overflow-visible',
        extra: 'flex-1 w-0 ml-2 flex items-center justify-end',
        header: 'px-5 py-3 z-1 min-h-0',
        body: `px-5 py-4 ${bodyClassName ?? ''}`
      }}
      title={
        <div className="flex items-center gap-2">
          {icon && <span className="flex shrink-0">{icon}</span>}
          <span className="text-[15px] font-semibold text-msa-text-1">
            {title}
          </span>
          {typeof count === 'number' && (
            <span className="text-xs font-normal text-msa-text-3">
              ({count})
            </span>
          )}
          {badge && (
            /* fill-5 rather than fill-purple: the latter is #edefff / #141414, i.e.
               within ~1.1 contrast of the card surface in BOTH themes, so the
               chip shape was invisible and only its text showed. */
            <span className="rounded bg-msa-fill-5 px-1.5 py-0.5 text-[10px] font-normal text-msa-text-brand1">
              {badge}
            </span>
          )}
        </div>
      }
      extra={
        <div className="max-w-full flex items-center">
          {onEdit && (
            <Tooltip title={t.widgets.edit}>
              <IconButton
                icon={<EditIcon className="h-4 w-4" />}
                variant="ghost"
                size="sm"
                onClick={onEdit}
              />
            </Tooltip>
          )}
          {extra}
        </div>
      }
    >
      {children}
    </Card>
  )
}
