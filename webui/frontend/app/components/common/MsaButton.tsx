import { Button } from 'antd'
import type { ButtonProps } from 'antd'
import { forwardRef } from 'react'

/* ================================================================
 * MsaButton — Base button
 *
 * Wraps antd Button with:
 *   1. Removed default border / shadow
 *   2. Five color variants (primary / filled / tonal / outlined / ghost)
 *   3. antd click ripple effect
 *
 * Size, radius, spacing are all controlled via external className.
 * ================================================================ */

export interface MsaButtonProps extends Omit<ButtonProps, 'type' | 'variant'> {
  /**
   * Color variant:
   * - `primary`   Deep purple background (purple-10) + white text
   * - `filled`    White/surface background (text-0) + dark text, hover fill-3
   * - `tonal`     Gray fill (fill-2) + dark text (default)
   * - `outlined`  Transparent background + border + dark text
   * - `ghost`     Transparent background + secondary text color
   */
  variant?: 'primary' | 'filled' | 'tonal' | 'outlined' | 'ghost'
}

const variantStyles: Record<string, string> = {
  primary:
    'bg-msa-purple-10 text-white disabled:cursor-not-allowed disabled:opacity-40',
  filled:
    'bg-msa-fill-0 text-msa-text-1 hover:bg-msa-fill-3 disabled:cursor-not-allowed disabled:text-msa-text-disabled disabled:hover:bg-msa-text-0',
  tonal:
    'bg-msa-fill-2 text-msa-text-1 hover:bg-msa-fill-3 disabled:cursor-not-allowed disabled:text-msa-text-disabled disabled:hover:bg-msa-fill-2',
  outlined:
    'bg-msa-fill-0 !border !border-solid !border-msa-line-1 text-msa-text-1 hover:bg-msa-fill-2 disabled:cursor-not-allowed disabled:text-msa-text-disabled',
  ghost:
    'bg-transparent text-msa-text-2 hover:bg-msa-fill-2 disabled:cursor-not-allowed disabled:text-msa-text-disabled disabled:hover:bg-transparent'
}

export const MsaButton = forwardRef<HTMLButtonElement, MsaButtonProps>(
  ({ variant = 'tonal', className = '', classNames, ...rest }, ref) => {
    const extraClassNames =
      classNames && typeof classNames === 'object'
        ? (classNames as Record<string, string>)
        : {}
    const extraIcon =
      typeof extraClassNames.icon === 'string' ? extraClassNames.icon : ''
    return (
      <Button
        ref={ref}
        type="text"
        className={`${variant === 'outlined' ? 'shadow-none' : 'border-none shadow-none'} ${variantStyles[variant]} ${className}`}
        classNames={{
          ...extraClassNames,
          icon: `flex items-center justify-center leading-none ${extraIcon}`
        }}
        {...rest}
      />
    )
  }
)

MsaButton.displayName = 'MsaButton'
