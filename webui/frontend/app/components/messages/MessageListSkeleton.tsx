import { Skeleton } from 'antd'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import type { ChatMessageItem } from './MessageList'

/**
 * One skeleton row mimicking a chat bubble: a rounded content block, no avatar
 * (the real Bubble.List renders none). `mine` flips it to the right (user)
 * side, matching the real placement (assistant start / user end).
 */
function SkeletonRow({
  mine,
  rows,
  width
}: {
  mine?: boolean
  rows: number
  width: number
}) {
  return (
    <div className={`flex items-start ${mine ? 'justify-end' : ''}`}>
      <div className="rounded-2xl bg-msa-fill-2 px-4 py-3" style={{ width }}>
        <Skeleton active title={false} paragraph={{ rows }} />
      </div>
    </div>
  )
}

/** Approximate the bubble's line count from its content length. */
function estimateRows(len: number): number {
  return Math.max(1, Math.min(4, Math.ceil(len / 80)))
}

/** Approximate the bubble's width from its content length (side-capped). */
function estimateWidth(len: number, mine: boolean): number {
  const max = mine ? 280 : 440
  return Math.min(max, Math.max(120, len * 7))
}

/**
 * Loading placeholder for the chat message list, shown while history hydrates
 * (see ChatPanel). Renders one skeleton bubble per real message so the count
 * and left/right placement (by `role`) match the conversation about to appear.
 * Occupies the same flex-1 slot as MessageList (the surrounding chat layout
 * provides the centered column and the SSR-safe composer stays mounted below).
 */
export function MessageListSkeleton({ items }: { items: ChatMessageItem[] }) {
  return (
    <DeferredSkeleton className="flex min-h-0 flex-1 flex-col gap-6 overflow-hidden py-6">
      {items.map(({ id, message }) => {
        const mine = message.role === 'user'
        const len = message.content?.length ?? 0
        return (
          <SkeletonRow
            key={id}
            mine={mine}
            rows={estimateRows(len)}
            width={estimateWidth(len, mine)}
          />
        )
      })}
    </DeferredSkeleton>
  )
}
