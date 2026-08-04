import { Skeleton } from 'antd'
import { DeferredSkeleton } from './DeferredSkeleton'

interface CardSkeletonGridProps {
  /** Number of skeleton cards to render */
  count?: number
  /** Grid column class names (default: 3-col responsive for settings pages) */
  className?: string
}

/**
 * CardSkeletonGrid — Loading placeholder for card grid lists.
 * Used while card data is being fetched.
 */
export function CardSkeletonGrid({
  count = 6,
  className = 'grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
}: CardSkeletonGridProps) {
  return (
    <DeferredSkeleton className={className}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl bg-msa-fill-2 p-4">
          <Skeleton active paragraph={{ rows: 1 }} title={{ width: '40%' }} />
        </div>
      ))}
    </DeferredSkeleton>
  )
}
