import { Button, Dropdown, Popconfirm, Tooltip, Typography } from 'antd'
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
  /** undefined = not probed yet; the reason rides in `healthError`. */
  healthy?: boolean
  healthError?: string | null
  /** A probe is in flight — connecting/installing is a real phase (a cold uvx
      server takes tens of seconds), and without showing it the card reads as
      "fine" right up until it flips to failed. Surfaced on the reconnect
      button, the same place a manual probe reports, so it needs `onReconnect`
      to have somewhere to land. */
  probing?: boolean
}

export function McpCard({
  mcp,
  onToggle,
  onReconnect,
  onEdit,
  onRemove,
  healthy,
  healthError,
  probing
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
      /* Only a click that actually landed inside the card toggles the server.
         antd renders tooltips and menus into a portal on `document.body`, yet
         React keeps bubbling their events up THIS component tree — so reading
         the failure reason in a tooltip and clicking it (to select the URL, say)
         used to flip the server off. One containment check covers every popup
         the card owns, present and future; a `stopPropagation` per popup only
         ever covers the node it is attached to, and misses the tooltip's own
         padding and arrow. */
      onClick={(e) => {
        if (!e.currentTarget.contains(e.target as Node)) return
        onToggle(!mcp.enabled)
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          {/* Reachability as a dot, with the provider's own words on hover.
              A dead endpoint used to be indistinguishable from a healthy one
              here — same card, same green switch — while the model silently
              lost its tools. A dot is the smallest thing that fixes that.
              Purely a verdict: an in-flight probe spins the reconnect button
              instead, so one visual language covers both the automatic sweep
              and a manual retry (see `probing`). Deliberately NO placeholder
              when there is no verdict — reserving the slot on every card would
              indent every name 12px off the description line beneath it, and
              that misalignment reads worse than the name shifting once, at the
              moment a dot appears. */}
          {mcp.enabled && healthy === false ? (
            <Tooltip title={healthError || t.resources.statusError}>
              <span
                aria-label={t.resources.statusError}
                className="h-1.5 w-1.5 rounded-full bg-msa-deco-red"
              />
            </Tooltip>
          ) : null}
          <span className="truncate text-sm font-medium text-msa-text-1">
            {mcp.name}
          </span>
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <MsaSwitch checked={mcp.enabled} onChange={onToggle} />
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        {/* An unhealthy card trades its description line for the reason, and
            carries the full text on hover because this line is the ONLY place
            it appears — nothing else in the UI reports it, so whatever the
            truncation cut is simply lost. The status dot holds the same tooltip,
            but at 6px across it is nearly impossible to aim at, and a truncated
            `412 ... for url 'https://…'` hides exactly the part that identifies
            the failure. An in-flight probe does NOT take this line over: the
            spinning reconnect button already says so, and blanking the
            description for it just makes the card flicker.

            `ellipsis` rather than a bare Tooltip: antd measures the node and
            attaches one only when the text is ACTUALLY cut, so a short reason
            ("Connection refused") stays hover-free instead of popping up a
            repeat of what is already on screen.

            The description line gets no tooltip: it is prose the user wrote and
            can reopen in the edit dialog, not a diagnostic that exists nowhere
            else. */}
        {mcp.enabled && healthy === false && healthError ? (
          <Typography.Text
            className="min-w-0 flex-1 !text-xs !text-msa-deco-red"
            ellipsis={{
              /* Wrapped so the newline survives: these reasons arrive
                 multi-line (httpx puts the status and URL on one line, a "For
                 more information check: …" link on the next) and the tooltip's
                 default `normal` would collapse it into a space, running the
                 two sentences together mid-URL. */
              tooltip: {
                title: (
                  <span className="whitespace-pre-line">{healthError}</span>
                )
              }
            }}
          >
            {healthError}
          </Typography.Text>
        ) : (
          <span className="min-w-0 flex-1 truncate text-xs text-msa-text-3">
            {mcp.description || t.resources.noDescription}
          </span>
        )}
        <div
          className="flex shrink-0 items-center gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          {onReconnect && (
            /* One spinner for every probe, whoever started it: the sweep on
               mount, the deep check after an add, or this button. antd also
               blocks the click while it spins, so a manual retry cannot race
               the sweep that is already probing the same server. */
            <Tooltip
              title={probing ? t.resources.probing : t.resources.reconnect}
            >
              <Button
                size="small"
                type="text"
                icon={<RefreshIcon className="h-5 w-5" />}
                loading={testing || probing}
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
        </div>
      </div>
    </div>
  )
}
