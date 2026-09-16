import type { ConfigProviderProps } from 'antd'
import type { ReactNode } from 'react'
import emptyLight from '~/assets/images/empty-light.png'
import emptyDark from '~/assets/images/empty-dark.png'
import chatEmptyLight from '~/assets/images/chat-empty-light.png'
import chatEmptyDark from '~/assets/images/chat-empty-dark.png'
import { useT } from '~/lib/i18n'
import { useTheme } from '~/lib/theme'
import { MsaButton, type MsaButtonProps } from './MsaButton'

export type EmptyStateSize = 'xs' | 'sm' | 'md' | 'lg'

/** Which illustration to show. `box` is the generic "nothing here"; `chat` is for
 * conversation lists, where a speech bubble reads better than a crate. */
export type EmptyStateArt = 'box' | 'chat'

const ART: Record<EmptyStateArt, { light: string; dark: string }> = {
  box: { light: emptyLight, dark: emptyDark },
  chat: { light: chatEmptyLight, dark: chatEmptyDark }
}

const IMG_SIZE: Record<EmptyStateSize, string> = {
  xs: 'h-[96px]',
  sm: 'h-[160px]',
  md: 'h-[200px]',
  lg: 'h-[240px]'
}

const PADDING: Record<EmptyStateSize, string> = {
  xs: 'py-3',
  sm: 'py-6',
  md: 'py-10',
  lg: 'py-16'
}

/** The description tracks the size variant: at `sm` (a sidebar group, a popover)
 * the body text sits next to 12px UI copy, where `text-sm` reads oversized. */
const TEXT_SIZE: Record<EmptyStateSize, string> = {
  xs: 'text-xs',
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-sm'
}

/** The gap under the illustration shrinks with it — `xs` lives inside a dropdown
 * panel, where 16px of air makes the two-line block look unanchored. */
const TEXT_GAP: Record<EmptyStateSize, string> = {
  xs: 'mt-1',
  sm: 'mt-4',
  md: 'mt-4',
  lg: 'mt-4'
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
        <p className={`${TEXT_GAP[size]} ${TEXT_SIZE[size]} text-msa-text-3`}>
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/**
 * The call-to-action inside an EmptyState: a pill-shaped primary button.
 *
 * Lives here so an empty list offers the same affordance everywhere instead of
 * each caller re-deriving the radius and padding — and so "nothing here" always
 * comes with the one thing that fixes it, rather than prose pointing at a
 * button somewhere else on the page.
 */
export function EmptyStateAction({
  className = '',
  ...rest
}: MsaButtonProps) {
  return (
    <MsaButton
      variant="primary"
      className={`h-auto rounded-full px-6 py-2 ${className}`}
      {...rest}
    />
  )
}

/** The components antd asks `renderEmpty` about (Select, Table, Cascader, …). */
type AntdEmptyComponent = Parameters<
  NonNullable<ConfigProviderProps['renderEmpty']>
>[0]

/**
 * The project empty state, in the shape antd's `ConfigProvider.renderEmpty`
 * wants — wired once in `root.tsx`.
 *
 * antd's data components render their own empty state (its grey crate plus
 * "No data") whenever a caller passes no `notFoundContent` / `locale.emptyText`,
 * so the default kept surfacing in Select dropdowns and table bodies no matter
 * how many call sites were converted by hand. Overriding it centrally is the
 * only version of this that stays fixed as new Selects and Tables get written.
 *
 * Sizing follows antd's own split: list and table bodies have room for the
 * illustration, popup panels get the compact one.
 */
export function AntdRenderEmpty({
  componentName
}: {
  componentName?: AntdEmptyComponent
}) {
  const { t } = useT()
  // A filter dropdown supplies its own empty state and antd's default renders
  // nothing here on purpose (the call site coalesces on nullish) — returning an
  // illustration would stack a second one inside the filter panel.
  if (componentName === 'Table.filter') return null
  const inList = componentName === 'Table' || componentName === 'List'
  return <EmptyState size={inList ? 'sm' : 'xs'} description={t.common.noData} />
}

/** Ready to hand to `ConfigProvider.renderEmpty`. A module-level constant
 * because antd keys its config context on this function's identity — an inline
 * lambda would rebuild the context, and every consumer with it, on each render
 * of the provider. */
export const renderAntdEmpty: NonNullable<
  ConfigProviderProps['renderEmpty']
> = (componentName) => <AntdRenderEmpty componentName={componentName} />
