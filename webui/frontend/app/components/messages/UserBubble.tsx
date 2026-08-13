import { FileCard } from '~/components/common/FileCard'
import type { AgentMessage } from '~/lib/agentProvider'
import type { OnOpenFile } from '~/components/messages/types'
import { useT } from '~/lib/i18n'
import { useWorkspaceFileSet } from '~/lib/workspaceFiles'

/** User message bubble content (right-aligned, preserves line breaks). Any
 * files the user attached this turn render as cards above the text; media use
 * the workspace raw URL for an inline preview. Non-deleted cards are clickable
 * and open the file in the workspace rail. On history replay a file whose
 * workspace entry has since been deleted (`exists === false`) falls back to a
 * generic card with a "deleted" note and is not clickable. */
export function UserBubble({
  message,
  onOpenFile
}: {
  message: AgentMessage
  onOpenFile?: OnOpenFile
}) {
  const { t } = useT()
  const files = message.files ?? []
  // Live workspace path set: deletions/renames/creations flip the cards'
  // deleted state immediately (fallback: the server-baked `exists` flag).
  const fileSet = useWorkspaceFileSet()
  return (
    <div className="flex flex-col gap-2">
      {files.length > 0 && (
        <div className="flex flex-wrap items-start justify-end gap-2">
          {files.map((f) => {
            const deleted = fileSet
              ? !fileSet.has(f.path)
              : f.exists === false
            const card = (
              <FileCard
                name={f.name}
                byte={f.size}
                type={f.type ?? 'file'}
                src={f.url}
                deleted={deleted}
                note={deleted ? t.home.fileDeleted : undefined}
              />
            )
            if (deleted || !onOpenFile) {
              return (
                <div key={f.path} className={deleted ? 'cursor-not-allowed' : ''}>
                  {card}
                </div>
              )
            }
            return (
              <div
                key={f.path}
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
                className="group/filecard cursor-pointer rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-msa-line-2"
              >
                {card}
              </div>
            )
          })}
        </div>
      )}
      {message.segments && message.segments.length > 0 ? (
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
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
          <div className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.content}
          </div>
        )
      )}
    </div>
  )
}
