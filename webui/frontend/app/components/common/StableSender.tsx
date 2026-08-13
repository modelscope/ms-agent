import { Sender } from '@ant-design/x'
import type { SenderProps } from '@ant-design/x/es/sender'
import { useMemo } from 'react'

const LINE_HEIGHT = 22
const PADDING_BLOCK = 5

/** Imperative handle exposed by Sender (focus/insert/getValue…). */
export type SenderHandle = React.ComponentRef<typeof Sender>

type StableSenderProps = SenderProps & {
  /** Imperative Sender handle (insert/focus/getValue) — needed in slot mode
   * where `value` is uncontrolled. React 19: ref is a regular prop. */
  ref?: React.Ref<React.ComponentRef<typeof Sender>>
}

export function StableSender(props: StableSenderProps) {
  const { autoSize, classNames, styles, ref, ...rest } = props

  const minRows = typeof autoSize === 'object' ? (autoSize.minRows ?? 1) : 1

  const mergedClassNames = useMemo(
    () => ({
      ...classNames,
      input: `resize-none ${classNames?.input ?? ''}`
    }),
    [classNames]
  )

  const mergedStyles = useMemo(
    () => ({
      ...styles,
      input: {
        minHeight: LINE_HEIGHT * minRows + PADDING_BLOCK * 2,
        ...styles?.input
      }
    }),
    [styles, minRows]
  )

  return (
    <Sender
      ref={ref}
      autoSize={autoSize}
      classNames={mergedClassNames}
      styles={mergedStyles}
      {...rest}
    />
  )
}

StableSender.Header = Sender.Header
