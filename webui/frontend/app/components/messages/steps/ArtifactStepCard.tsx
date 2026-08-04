import { FileTypeIcon, formatFileSize } from '~/components/common/FileCard'
import type { AgentStep } from '~/lib/agentProvider'
import type { OnOpenStep } from '../types'
import JumpIcon from '~/assets/icons/jump.svg?react'

/**
 * File / artifact step card: standard file card look (icon + name + type/size)
 * with an optional preview thumbnail. Clicking opens the workspace rail.
 */
export function ArtifactStepCard({
  step,
  onOpenStep
}: {
  step: AgentStep
  onOpenStep?: OnOpenStep
}) {
  const meta = step.meta
  const name = String(meta.name ?? '')
  const fileType =
    typeof meta.file_type === 'string'
      ? meta.file_type.toUpperCase()
      : (name.split('.').pop()?.toUpperCase() ?? 'FILE')
  const byte = typeof meta.byte === 'number' ? meta.byte : undefined
  const preview = typeof meta.preview === 'string' ? meta.preview : undefined

  return (
    <button
      type="button"
      onClick={() => onOpenStep?.(step)}
      className="group flex w-fit max-w-[320px] cursor-pointer flex-col gap-2 rounded-xl border border-msa-line-1 bg-msa-fill-2 p-2.5 text-left transition-colors hover:bg-msa-fill-3"
    >
      <div className="flex items-center gap-3">
        <FileTypeIcon name={name} className="h-9 w-9 shrink-0" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm text-msa-text-1">{name}</span>
          <span className="mt-0.5 text-xs text-msa-text-3">
            {fileType}
            {byte != null && `  ${formatFileSize(byte)}`}
          </span>
        </div>
        <JumpIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
      </div>
      {preview && (
        <div className="overflow-hidden rounded-lg border border-msa-line-1">
          <img src={preview} alt={name} className="w-full object-cover" />
        </div>
      )}
    </button>
  )
}
