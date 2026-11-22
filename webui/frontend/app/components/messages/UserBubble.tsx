import { Tooltip } from 'antd'
import { FileCard } from '~/components/common/FileCard'
import type { AgentMessage, ChatFileRef } from '~/lib/agentProvider'
import type { OnOpenFile } from '~/components/messages/types'
import { useT } from '~/lib/i18n'
import { useFileExists } from '~/lib/workspaceFiles'
import { useImageDelivery } from '~/lib/imageDelivery'

/**
 * "This picture did not reach the model."
 *
 * The single most useful thing this area was missing. Whether an attached image
 * actually entered the request was decided deep in the transport, written down
 * nowhere, and communicated to the user only by the model — in sentences it made
 * up. So "I can't see the image" could mean the switch was off, the endpoint had
 * refused, or the model was simply confabulating, and nothing on screen told
 * them apart. Each has a different remedy.
 *
 * Deliberately a corner dot rather than a banner: the normal case is silence,
 * and a conversation that switched models mid-way then explains its own history
 * — the turns the model could see have no dot, the ones it could not do.
 *
 * The dot means "the model has never received this picture", not "not on this
 * turn": once an image has been shown the record does not go back, so turning
 * the switch on clears the badge and the user can see that it worked.
 *
 * Subscribes to the live map itself rather than receiving it from the card, so a
 * delivery report mid-turn re-renders one dot instead of every attachment.
 */
function DeliveryBadge({
  path,
  recorded
}: {
  path: string
  recorded?: string
}) {
  const { t } = useT()
  const delivery = useImageDelivery().get(path) ?? recorded
  if (!delivery || delivery === 'delivered') return null
  const label =
    delivery === 'unreadable' ? t.chat.imageUnreadable : t.chat.imageNotSent
  return (
    <Tooltip title={label}>
      <span
        aria-label={label}
        className="absolute left-1 top-1 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white dark:ring-msa-bg-1"
      />
    </Tooltip>
  )
}

/** A single attached-file card with LIVE existence: a webui rename/delete flips
 * it to the disabled "deleted" card immediately. Uses the shared `useFileExists`
 * guard (a missing path is only "deleted" when the workspace listing actually
 * covers its directory), NOT a bare `!fileSet.has(path)` membership test which
 * mis-flags live files whenever the listing lags or its path root differs. */
function UserFileCard({
  file: f,
  onOpenFile
}: {
  file: ChatFileRef
  onOpenFile?: OnOpenFile
}) {
  const { t } = useT()
  const deleted = !useFileExists(f.path, f.exists !== false)
  // A deleted file always falls back to the doc card, so it follows the
  // document branch below regardless of its original type.
  const isMedia =
    !deleted &&
    (f.type === 'image' || f.type === 'audio' || f.type === 'video')
  const card = (
    <FileCard
      name={f.name}
      byte={f.size}
      type={f.type ?? 'file'}
      src={f.url}
      deleted={deleted}
      note={deleted ? t.home.fileDeleted : undefined}
      onOpen={isMedia && onOpenFile ? () => onOpenFile(f.path) : undefined}
    />
  )
  // Media is NOT wrapped in a whole-card control: the picture/player owns its
  // own clicks (antd preview, native controls), so the open-in-workspace action
  // is a corner button inside the card instead. Wrapping it would put a handler
  // and a tooltip over an area the user is actually clicking for something else.
  if (isMedia) {
    return (
      <div className="relative">
        {card}
        <DeliveryBadge path={f.path} recorded={f.delivery} />
      </div>
    )
  }
  // The wrappers below are the flex items of the attachment row, so the card's
  // `min-w-0` has to be repeated here — otherwise the shrink stops at this layer
  // and the card still overflows the bubble.
  if (deleted || !onOpenFile) {
    return (
      <div className={`min-w-0 ${deleted ? 'cursor-not-allowed' : ''}`}>
        {card}
      </div>
    )
  }
  return (
    <div
      role="button"
      tabIndex={0}
      title={t.session.openInWorkspace}
      onClick={() => onOpenFile(f.path)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpenFile(f.path)
        }
      }}
      className="group/filecard min-w-0 cursor-pointer rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-msa-line-2"
    >
      {card}
    </div>
  )
}

/** User message bubble content (right-aligned, preserves line breaks). Any
 * files the user attached this turn render as cards above the text; media use
 * the workspace raw URL for an inline preview. Non-deleted cards are clickable
 * and open the file in the workspace rail. On history replay a file whose
 * workspace entry has since been deleted (`exists === false`) falls back to a
 * generic card with a "deleted" note and is not clickable. */
export function UserBubble({
  message,
  id,
  onOpenFile
}: {
  message: AgentMessage
  /** Item key of this turn, stamped onto the root so the message navigator can
   * locate the bubble while tracking the reading position. */
  id?: string
  onOpenFile?: OnOpenFile
}) {
  const files = message.files ?? []
  return (
    <div className="flex flex-col gap-2" data-msa-msg-key={id}>
      {files.length > 0 && (
        <div className="flex flex-wrap items-start justify-end gap-2">
          {files.map((f) => (
            <UserFileCard key={f.path} file={f} onOpenFile={onOpenFile} />
          ))}
        </div>
      )}
      {message.segments && message.segments.length > 0 ? (
        <div className="whitespace-pre-wrap text-sm leading-[22px]">
          {message.segments.map((seg, i) =>
            seg.type === 'skill' ? (
              <span
                key={i}
                className="mr-1.5 inline-flex items-center rounded-md bg-msa-fill-2 px-1.5 py-0.5 font-mono text-xs text-msa-text-brand1"
              >
                /{seg.name || seg.id}
              </span>
            ) : (
              <span key={i}>{seg.text}</span>
            )
          )}
        </div>
      ) : (
        message.content && (
          <div className="whitespace-pre-wrap text-sm leading-[22px]">
            {message.content}
          </div>
        )
      )}
    </div>
  )
}
