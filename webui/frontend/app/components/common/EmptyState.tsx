import type { ReactNode } from 'react'
import emptyLight from '~/assets/images/empty-light.png'
import emptyDark from '~/assets/images/empty-dark.png'
import { useTheme } from '~/lib/theme'

export type EmptyStateSize = 'sm' | 'md' | 'lg'

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

interface Props {
  /** Image & spacing size variant */
  size?: EmptyStateSize
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
  description,
  action,
  className = ''
}: Props) {
  const { theme } = useTheme()

  return (
    <div
      className={`flex flex-col items-center justify-center ${PADDING[size]} ${className}`}
    >
      <img
        src={theme === 'dark' ? emptyDark : emptyLight}
        alt=""
        className={`${IMG_SIZE[size]} w-auto`}
      />
      {description && (
        <p className="mt-4 text-sm text-msa-text-3">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
