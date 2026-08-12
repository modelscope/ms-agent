import { Button, Dropdown, Popconfirm, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useState } from 'react'
import { MsaSwitch } from '~/components/common/MsaSwitch'
import { useT } from '~/lib/i18n'
import type { Mcp } from '~/lib/types'
import MoreIcon from '~/assets/icons/more.svg?react'
import RefreshIcon from '~/assets/icons/refresh.svg?react'

interface McpCardProps {
  mcp: Mcp
  onToggle: (v: boolean) => void
  onReconnect?: () => void
  onEdit?: () => void
  onRemove: () => void
}

export function McpCard({
  mcp,
  onToggle,
  onReconnect,
  onEdit,
  onRemove
}: McpCardProps) {
  const { t } = useT()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [testing, setTesting] = useState(false)

  const menu: MenuProps = {
    onClick: (e) => e.domEvent.stopPropagation(),
    items: [
      ...(onEdit
        ? [{ key: 'edit', label: t.resources.edit, onClick: onEdit }]
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
      onClick={() => onToggle(!mcp.enabled)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-msa-text-1">
          {mcp.name}
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <MsaSwitch checked={mcp.enabled} onChange={onToggle} />
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-msa-text-3">
          {mcp.description || t.resources.noDescription}
        </span>
        <div
          className="flex shrink-0 items-center gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          {onReconnect && mcp.transport !== 'stdio' && (
            <Tooltip title={t.resources.reconnect}>
              <Button
                size="small"
                type="text"
                icon={<RefreshIcon className="h-4 w-4" />}
                loading={testing}
                onClick={async () => {
                  setTesting(true)
                  try {
                    await onReconnect()
                  } finally {
                    setTesting(false)
                  }
                }}
                className="!text-msa-text-3"
              />
            </Tooltip>
          )}
          <Popconfirm
            title={t.resources.confirmRemoveMcp}
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
                />
              </Tooltip>
            </Dropdown>
          </Popconfirm>
        </div>
      </div>
    </div>
  )
}
