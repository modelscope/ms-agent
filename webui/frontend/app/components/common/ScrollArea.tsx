import type { ComponentPropsWithRef } from 'react'

export type ScrollAreaProps = ComponentPropsWithRef<'div'> & {
  /** Target inline gap on both edges, in px. Held equal under classic and
   * overlay scrollbars alike. */
  pad?: number
}

/* ==================================================================
 * ScrollArea — vertical scroll box whose rows keep the same left/right gap no
 * matter which scrollbar mode the OS uses.
 *
 * Two things have to hold at once:
 *   1. the gap must not jump when the list grows past the box — hence
 *      `scrollbar-gutter: stable`, which reserves the bar's slot up front;
 *   2. that slot must not *add* to the gap — hence the end padding subtracting
 *      the measured bar width back out, so `pad` is what you actually see.
 *
 * `max()` guards the case where `pad` is narrower than the bar: padding cannot
 * go negative, so the visible gap there is the bar width and the two edges
 * differ by the remainder. The bar is ~11px wide here (`scrollbar-width: thin`
 * on Chromium), so `pad` >= 12 balances exactly.
 *
 * Deliberately NOT `stable both-edges`: that mirrors the reserved slot onto the
 * start edge, which is symmetric but makes the gap `pad + bar` under classic
 * scrollbars and plain `pad` under overlay ones — the very inconsistency this
 * component removes.
 * ================================================================== */
export function ScrollArea({
  pad = 0,
  className = '',
  style,
  ...rest
}: ScrollAreaProps) {
  return (
    <div
      {...rest}
      className={`min-h-0 min-w-0 overflow-y-auto overflow-x-hidden ${className}`}
      style={{
        scrollbarGutter: 'stable',
        paddingInlineStart: pad,
        paddingInlineEnd: `max(0px, ${pad}px - var(--msa-scrollbar-w))`,
        ...style
      }}
    />
  )
}
