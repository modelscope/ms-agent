import { useLoaderData, useRevalidator } from 'react-router'
import { useState } from 'react'
import { ProjectOverviewView } from '~/components/project/ProjectOverviewView'
import { NewProjectModal } from '~/components/project/NewProjectModal'
import { api } from '~/lib/api'
import type { Project } from '~/lib/types'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/project-detail'

/** "<project name> · <brand>". */
export function meta({ loaderData, matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [
    { title: pageTitle(t, loaderData?.project?.name || t.pageTitle.project) }
  ]
}

export async function loader({ params }: Route.LoaderArgs) {
  const projectId = params.projectId as string
  const [project, sessions] = await Promise.all([
    api.getProject(projectId),
    api.listSessions(projectId)
  ])
  return { project, sessions }
}

export default function ProjectDetailPage() {
  const { project, sessions } = useLoaderData<typeof loader>()
  const revalidator = useRevalidator()
  const [editingProject, setEditingProject] = useState<Project | null>(null)

  return (
    <>
      <ProjectOverviewView
        project={project}
        sessions={sessions}
        onEditProject={(p) => setEditingProject(p)}
      />
      <NewProjectModal
        open={!!editingProject}
        project={editingProject ?? undefined}
        onClose={() => setEditingProject(null)}
        onCreated={() => {
          setEditingProject(null)
          revalidator.revalidate()
        }}
        onUpdated={() => {
          setEditingProject(null)
          revalidator.revalidate()
        }}
      />
    </>
  )
}
