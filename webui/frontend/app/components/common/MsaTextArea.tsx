import { Input } from 'antd'
import type { TextAreaProps } from 'antd/es/input'
import type { CSSProperties } from 'react'
import { useEffect, useState } from 'react'

const LINE_HEIGHT = 22
const PADDING_VERTICAL = 10 // paddingTop 4 + paddingBottom 4 + borderTop 1 + borderBottom 1

interface MsaTextAreaClassNames {
  root?: string
  textarea?: string
  clear?: string
  count?: string
}

interface MsaTextAreaStyles {
  root?: CSSProperties
  textarea?: CSSProperties
  clear?: CSSProperties
  count?: CSSProperties
}

interface MsaTextAreaProps extends Omit<
  TextAreaProps,
  'classNames' | 'styles'
> {
  classNames?: MsaTextAreaClassNames
  styles?: MsaTextAreaStyles
}

/**
 * Wrapper around antd Input.TextArea that prevents SSR hydration height flash.
 *
 * During SSR (before client mount), autoSize is disabled and a fixed height is
 * calculated from minRows (rows × lineHeight + padding). After mount, autoSize
 * takes over normally.
 */
export function MsaTextArea({
  autoSize,
  classNames: classNamesProp,
  styles: stylesProp,
  ...rest
}: MsaTextAreaProps) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    setMounted(true)
  }, [])

  // Compute fixed height for SSR phase: rows * lineHeight + padding
  const minRows =
    typeof autoSize === 'object' ? (autoSize.minRows ?? 2) : undefined
  const ssrHeight = minRows
    ? minRows * LINE_HEIGHT + PADDING_VERTICAL
    : undefined

  return (
    <Input.TextArea
      {...rest}
      autoSize={mounted ? autoSize : undefined}
      classNames={{
        ...classNamesProp,
        textarea: `resize-none ${classNamesProp?.textarea ?? ''}`
      }}
      styles={
        !mounted && ssrHeight
          ? {
              ...stylesProp,
              textarea: { height: ssrHeight, ...stylesProp?.textarea }
            }
          : stylesProp
      }
    />
  )
}
