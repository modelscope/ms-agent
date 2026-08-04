import { InstructionsCard } from '~/components/widgets/InstructionsCard'
import { MemoryCard } from '~/components/widgets/MemoryCard'
import type { Project, Scope } from '~/lib/types'

interface Props {
  project: Project
}

export function ProjectWidgetRail({ project }: Props) {
  const projectScope: Scope = `project:${project.id}`
  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-[20px] overflow-hidden">
      <InstructionsCard scope={projectScope} />
      <MemoryCard project={project} />
    </div>
  )
}
