import { Skeleton } from 'antd'

/**
 * DeferredSkeleton — the single entry point for loading skeletons.
 *
 * Every skeleton renders inside the anti-flicker gate (`.msa-loading-defer`,
 * app.css): invisible for the first 250ms — a fast load never flashes a
 * skeleton at all — then a 150ms fade-in for genuinely slow loads. Pure CSS,
 * so it is SSR-safe (no hydration timing).
 *
 * Two shapes:
 * - default: a standard antd paragraph skeleton (`rows`);
 * - `children`: a custom skeleton structure (card grids, table mocks, …) that
 *   only needs the gate, not the default paragraph.
 */
export function DeferredSkeleton({
  rows = 6,
  className = '',
  children
}: {
  /** Paragraph rows for the default antd skeleton (ignored with children). */
  rows?: number
  /** Extra classes on the gate wrapper (layout/padding of the placeholder). */
  className?: string
  children?: React.ReactNode
}) {
  return (
    <div className={`msa-loading-defer ${className}`}>
      {children ?? <Skeleton active title={false} paragraph={{ rows }} />}
    </div>
  )
}
