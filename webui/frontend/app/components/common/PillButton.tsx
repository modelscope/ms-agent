import { Tooltip } from 'antd'
import { forwardRef, useEffect, useRef, useState } from 'react'
import { MsaButton } from './MsaButton'
import type { MsaButtonProps } from './MsaButton'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

/* ================================================================
 * PillButton — Pill-shaped selector button (e.g. Model / MCP pills)
 *
 * rounded-full + icon + optional dropdown caret
 *
 * The label is width-capped and truncates with an ellipsis so a long
 * name (e.g. a full model id) stays compact on narrow layouts instead
 * of blowing out the composer row. The cap is container-relative (cqw,
 * resolved against the composer's @container) rather than viewport-
 * relative, so it still holds when the composer column is narrow but the
 * viewport is wide (e.g. a detail rail is open). A tooltip surfaces the
 * full text — but only when the label is actually clipped.
 * ================================================================ */

interface PillButtonProps extends Omit<MsaButtonProps, 'variant'> {
  /** Whether to show dropdown arrow (default true) */
  caret?: boolean
  /** Panel open state — flips the caret (same 180° + transition as the
   * accordion headers) so the pill reads as expanded. */
  open?: boolean
}

export const PillButton = forwardRef<HTMLButtonElement, PillButtonProps>(
  (
    {
      caret = true,
      open = false,
      children,
      className = '',
      classNames,
      ...rest
    },
    ref
  ) => {
    const labelRef = useRef<HTMLSpanElement>(null)
    const [clipped, setClipped] = useState(false)
    const [labelText, setLabelText] = useState('')
    useEffect(() => {
      const el = labelRef.current
      if (!el) return
      const measure = () => {
        setClipped(el.scrollWidth > el.clientWidth + 1)
        setLabelText(el.textContent ?? '')
      }
      measure()
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      return () => ro.disconnect()
    }, [children])

    const extra =
      classNames && typeof classNames === 'object'
        ? (classNames as Record<string, string>)
        : {}
    return (
      <MsaButton
        ref={ref}
        variant="tonal"
        className={`!flex !items-center !gap-1.5 !rounded-full !px-3 !py-1.5 !h-auto !text-xs !font-normal !max-w-[min(240px,55cqw)] min-w-0 ${className}`}
        classNames={{ ...extra, icon: `shrink-0 ${extra.icon ?? ''}` }}
        {...rest}
      >
        {/* Tooltip only engages when the label is clipped (empty title = no
            tooltip); it wraps the inner span, not the button, so it never
            conflicts with the selector Popover that triggers on the button. */}
        <Tooltip title={clipped ? labelText : ''}>
          <span ref={labelRef} className="min-w-0 flex-1 truncate">
            {children}
          </span>
        </Tooltip>
        {caret && (
          <ArrowDownIcon
            className={`h-2.5 w-2.5 shrink-0 text-msa-text-3 transition-transform duration-200 ${
              open ? 'rotate-180' : ''
            }`}
          />
        )}
      </MsaButton>
    )
  }
)

PillButton.displayName = 'PillButton'
