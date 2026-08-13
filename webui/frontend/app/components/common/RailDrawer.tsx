import { Drawer } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  /** Rail content — the workspace rail or a step-detail rail. */
  children: ReactNode
  /**
   * Drawer width. Defaults to the chat view's overlay width; a page with more
   * room to spare (the project detail workspace tab) can widen it.
   */
  size?: string
  /** Extra class on the drawer root, e.g. `xl:hidden` to bind it to a breakpoint. */
  rootClassName?: string
  /** antd passthrough — used to clear rail content only on a genuine close. */
  afterOpenChange?: (open: boolean) => void
  /** Drop the content when closed (a standalone drawer should not keep a stale file). */
  destroyOnHidden?: boolean
}

/**
 * Overlay presentation of a right rail.
 *
 * The rail components draw their own header (title, refresh, close) and fill
 * their container, so the antd chrome is switched off and the body padding
 * zeroed. That combination is easy to get wrong — a stacked second title, a
 * second close button, a panel collapsed to its content width — so it lives
 * here once and both callers (chat view below `xl`, project detail workspace
 * tab) share it.
 */
export function RailDrawer({
  open,
  onClose,
  children,
  size = 'min(720px, 92vw)',
  rootClassName,
  afterOpenChange,
  destroyOnHidden
}: Props) {
  return (
    <Drawer
      rootClassName={rootClassName}
      open={open}
      onClose={onClose}
      afterOpenChange={afterOpenChange}
      placement="right"
      size={size}
      closable={false}
      destroyOnHidden={destroyOnHidden}
      styles={{ body: { padding: 0 }, header: { display: 'none' } }}
    >
      {children}
    </Drawer>
  )
}
