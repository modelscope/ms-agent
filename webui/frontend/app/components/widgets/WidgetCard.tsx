import { Card, Tooltip } from 'antd'
import { IconButton } from '~/components/common/IconButton'
import { useT } from '~/lib/i18n'
import EditIcon from '~/assets/icons/edit.svg?react'

interface Props {
  title: string
  icon?: React.ReactNode
  count?: number
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
        </div>
      }
      extra={
        <div className="flex items-center">
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
