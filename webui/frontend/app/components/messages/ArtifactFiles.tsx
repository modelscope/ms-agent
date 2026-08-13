import { FileCard } from '~/components/common/FileCard'
import { useT } from '~/lib/i18n'
import { useWorkspaceFileSet } from '~/lib/workspaceFiles'
import type { OnOpenFile } from './types'

/**
 * The turn's deliverables: workspace files the agent wrote/edited during its
 * tool-call loop (`changed_files` from the loop_end boundary), rendered as
 * file cards after the summary. Reuses the attachment FileCard styling
 * (UserBubble's counterpart, left-aligned for the assistant side); cards open
 * the file in the workspace rail, and a file the user has since deleted
 * degrades to the disabled "deleted" card via the live workspace path set.
 */
export function ArtifactFiles({
  paths,
  onOpenFile
}: {
  paths: string[]
  onOpenFile?: OnOpenFile
}) {
  const { t } = useT()
  const fileSet = useWorkspaceFileSet()
  if (paths.length === 0) return null

  return (
    <div className="flex flex-wrap items-start gap-2">
      {paths.map((path) => {
        const name = path.split('/').pop() || path
        // Unknown set (provider not mounted yet) → assume it exists; the set
        // refresh flips the state as soon as it lands.
        const deleted = fileSet ? !fileSet.has(path) : false
        const card = (
          <FileCard
            name={name}
            deleted={deleted}
            note={deleted ? t.home.fileDeleted : undefined}
          />
        )
        if (deleted || !onOpenFile) {
          return (
            <div key={path} className={deleted ? 'cursor-not-allowed' : ''}>
              {card}
            </div>
          )
        }
        return (
          <div
            key={path}
            role="button"
            tabIndex={0}
            title={t.session.openInWorkspace}
            onClick={() => onOpenFile(path)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onOpenFile(path)
              }
            }}
            className="cursor-pointer rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-msa-line-2"
          >
            {card}
          </div>
        )
      })}
    </div>
  )
}
