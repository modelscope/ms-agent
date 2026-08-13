import { forwardRef } from 'react'
import { MsaButton } from './MsaButton'
import type { MsaButtonProps } from './MsaButton'

/* ================================================================
 * IconButton — Square icon-only button
 *
 * Based on MsaButton with preset square layout:
 *   - Centered icon
 *   - Configurable size (default 32px)
 *   - Rounded-xl border-radius
 *
 * Usage (icons come from app/assets/icons via `?react`, sized by class):
 *   <IconButton icon={<AddIcon className="h-4 w-4" />} />
 *   <IconButton icon={<SendIcon className="h-4 w-4" />} variant="primary" size="sm" />
 * ================================================================ */

interface IconButtonProps extends Omit<MsaButtonProps, 'size'> {
  /**
   * Predefined sizes:
   * - `xs`  20px (sidebar actions)
   * - `sm`  28px (compact)
   * - `md`  32px (default)
   * - `lg`  40px
   */
  size?: 'xs' | 'sm' | 'md' | 'lg'
  /** Stop click event from bubbling to parent elements. Default: true */
  stopPropagation?: boolean
}

const sizeStyles: Record<string, string> = {
  xs: 'h-5 w-5 min-w-0 rounded-md text-xs',
  sm: 'h-7 w-7 min-w-0 rounded-lg text-xs',
  md: 'h-8 w-8 min-w-0 rounded-xl text-sm',
  lg: 'h-10 w-10 min-w-0 rounded-xl text-base'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    {
      size = 'md',
      variant = 'ghost',
      stopPropagation = true,
      className = '',
      onClick,
      ...rest
    },
    ref
  ) => {
    const noHoverBg = variant === 'ghost' ? 'hover:bg-transparent' : ''
    // Icon centering is handled by the base MsaButton; here we only add the
    // square layout + size preset. Any caller `classNames` flows via `...rest`.
    return (
      <MsaButton
        ref={ref}
        variant={variant}
        className={`flex items-center justify-center p-0 ${sizeStyles[size]} ${noHoverBg} ${className}`}
        onClick={(e) => {
          if (stopPropagation) {
            e.stopPropagation()
            e.preventDefault()
          }
          onClick?.(e)
        }}
        {...rest}
      />
    )
  }
)

IconButton.displayName = 'IconButton'
