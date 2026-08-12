import type { ReactNode } from 'react'
import emptyLight from '~/assets/images/empty-light.png'
import emptyDark from '~/assets/images/empty-dark.png'
import chatEmptyLight from '~/assets/images/chat-empty-light.png'
import chatEmptyDark from '~/assets/images/chat-empty-dark.png'
import { useTheme } from '~/lib/theme'

export type EmptyStateSize = 'sm' | 'md' | 'lg'

/** Which illustration to show. `box` is the generic "nothing here"; `chat` is for
 * conversation lists, where a speech bubble reads better than a crate. */
export type EmptyStateArt = 'box' | 'chat'

const ART: Record<EmptyStateArt, { light: string; dark: string }> = {
  box: { light: emptyLight, dark: emptyDark },
  chat: { light: chatEmptyLight, dark: chatEmptyDark }
}

const IMG_SIZE: Record<EmptyStateSize, string> = {
  sm: 'h-[160px]',
  md: 'h-[200px]',
  lg: 'h-[240px]'
}

const PADDING: Record<EmptyStateSize, string> = {
  sm: 'py-6',
  md: 'py-10',
  lg: 'py-16'
}

/** The description tracks the size variant: at `sm` (a sidebar group, a popover)
 * the body text sits next to 12px UI copy, where `text-sm` reads oversized. */
const TEXT_SIZE: Record<EmptyStateSize, string> = {
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-sm'
}

interface Props {
  /** Image & spacing size variant */
  size?: EmptyStateSize
  /** Illustration variant (defaults to the generic empty box) */
  art?: EmptyStateArt
  /** Description text below the empty icon */
  description?: string
  /** Optional action button rendered below the description */
  action?: ReactNode
  /** Custom className for outer container */
  className?: string
}

/**
 * EmptyState — Unified empty state component.
 *
 * Shows a fixed empty-box illustration, an optional description,
 * and an optional action button (passed in as ReactNode).
 */
export function EmptyState({
  size = 'md',
  art = 'box',
  description,
  action,
  className = ''
}: Props) {
  const { theme } = useTheme()
  const src = ART[art][theme === 'dark' ? 'dark' : 'light']

  return (
    <div
      className={`flex flex-col items-center justify-center ${PADDING[size]} ${className}`}
    >
      <img src={src} alt="" className={`${IMG_SIZE[size]} w-auto`} />
      {description && (
        <p className={`mt-4 ${TEXT_SIZE[size]} text-msa-text-3`}>
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
