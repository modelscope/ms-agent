import { Popover, Tooltip } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useT } from '~/lib/i18n'
import { useMcpHealth } from '~/lib/mcpHealth'
import type { Mcp, Project } from '~/lib/types'
import { PillButton } from './PillButton'
import McpSelectIcon from '~/assets/icons/mcp-select.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

interface McpSelectorProps {
  items: Mcp[]
  project?: Project | null
}

/**
 * Read-only view of the MCP services active for this chat. Enablement lives
 * ONLY in project settings and global settings — the composer has no per-chat
 * toggles; it lists what those settings resolved to and links to the right
 * settings page (project tab when a project is selected, else global).
 */
export function McpSelector({ items, project }: McpSelectorProps) {
  const { t } = useT()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  // Only MCPs enabled in global/project settings apply to the chat.
  const enabledItems = useMemo(() => items.filter((m) => m.enabled), [items])

  // Reachability. An enabled-but-dead server is dropped before the model ever
  // sees it, so counting enablement alone made the pill claim tools that did
  // not exist — "5 MCP" while the model had one.
  //
  // Resolved on mount rather than when the popover opens: the whole value here
  // is being told WITHOUT having to ask, and a signal you only see after
  // clicking is one you never see. Non-blocking (the pill renders the plain
  // count until it lands), and it reads the sweep shared with the MCP pages
  // (`useMcpHealth`) — this pill mounts on every chat page, so sweeping per
  // mount re-probed every server just for walking between conversations.
  // The shared cache also re-sweeps on `msa:mcp-skill-changed`, which the
  // enabled list already refreshes on: without that, a server enabled a minute
  // ago kept whatever verdict the mount-time sweep gave it.
  const { rows: health, sweeping } = useMcpHealth()

  const deadCount = useMemo(
    () => enabledItems.filter((m) => health[m.id]?.healthy === false).length,
    [enabledItems, health]
  )
  const liveCount = enabledItems.length - deadCount

  const settingsPath = project
    ? `/projects/${project.id}?tab=mcps`
    : '/settings/mcp-skills?tab=mcps'

  const content = (
    <div className="w-[min(280px,calc(100vw-32px))]">
      {/* Header: title only — enablement is settings-driven. With nothing
          enabled the title itself states that, so no list section follows. */}
      <div className="flex items-center gap-1.5 px-[14px] py-[14px]">
        {enabledItems.length ? (
          <span className="text-xs text-msa-text-2">
            {t.home.mcpPopoverTitle}
          </span>
        ) : (
          <span className="text-xs font-medium text-msa-text-3">
            {t.home.mcpPopoverEmpty}
          </span>
        )}
        {/* The sweep is in flight: connecting/installing is a real phase for
            a cold stdio server, and without a signal the list reads as "all
            fine" right up until rows get struck through. */}
        {sweeping && enabledItems.length ? (
          <Tooltip title={t.resources.probing}>
            <SpinnerIcon className="h-3 w-3 shrink-0 animate-spin text-msa-text-3" />
          </Tooltip>
        ) : null}
      </div>

      <div className="h-px bg-msa-line-1" />

      {/* List — omitted entirely when empty; a placeholder row would only
          repeat what the header already said. */}
      {enabledItems.length ? (
        <>
          <div className="max-h-[280px] overflow-y-auto p-[6px]">
            {enabledItems.map((it) => {
              const dead = health[it.id]?.healthy === false
              return (
                <div
                  key={it.id}
                  className="flex items-center gap-2 rounded-[8px] px-[10px] py-2.5"
                >
                  <span
                    className={`min-w-0 flex-1 truncate text-sm ${
                      dead ? 'text-msa-text-3 line-through' : 'text-msa-text-1'
                    }`}
                  >
                    {it.name}
                  </span>
                  {/* The reason, on hover — the row already says "unavailable"
                      by being struck through. */}
                  {dead ? (
                    <Tooltip title={health[it.id]?.error || ''}>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-msa-deco-red" />
                    </Tooltip>
                  ) : null}
                </div>
              )
            })}
          </div>

          <div className="h-px bg-msa-line-1" />
        </>
      ) : null}

      {/* Footer: settings link */}
      <div className="px-[14px] py-[14px]">
        <span
          className="cursor-pointer text-xs text-msa-text-brand1"
          onClick={() => {
            setOpen(false)
            navigate(settingsPath)
          }}
        >
          {t.home.mcpSettings}
        </span>
      </div>
    </div>
  )

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      classNames={{ container: 'p-0' }}
      content={content}
    >
      <PillButton
        open={open}
        icon={
          <McpSelectIcon className="h-4 w-4 text-msa-text-3 dark:text-msa-purple-10" />
        }
      >
        {/* Plain count while everything answers; a fraction the moment some
            server does not, so the discrepancy is visible without the pill
            growing noisier for the healthy majority. */}
        {deadCount > 0
          ? `${liveCount}/${enabledItems.length}`
          : enabledItems.length}{' '}
        {t.home.mcpPill}
      </PillButton>
    </Popover>
  )
}
