import { InstructionsCard } from '~/components/widgets/InstructionsCard'
import { MemoryCard } from '~/components/widgets/MemoryCard'
import { MemoryDocCard } from '~/components/widgets/MemoryDocCard'
import type { Project, Scope } from '~/lib/types'

interface Props {
  project: Project
}

export function ProjectWidgetRail({ project }: Props) {
  const projectScope: Scope = `project:${project.id}`
  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-[20px] overflow-hidden">
      <InstructionsCard scope={projectScope} />
      {/* Two shapes of memory, chosen by the project's storage backend:
          - file:   memory IS one markdown file the agent reads — preview it and
                    edit the whole document in a drawer;
          - vector: individually embedded memories, written by the agent's own
                    fact extraction — a read-only list whose only action is
                    removing one the agent got wrong. */}
      {project.memory_backend === 'vector' ? (
        <MemoryCard project={project} />
      ) : (
        <MemoryDocCard project={project} />
      )}
    </div>
  )
}
