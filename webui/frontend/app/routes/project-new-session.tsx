import { useLoaderData } from 'react-router'
import { ChatView } from '~/components/chat/ChatView'
import { api } from '~/lib/api'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/project-new-session'

/** "<new chat> · <project name> · <brand>". */
export function meta({ loaderData, matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [
    { title: pageTitle(t, t.pageTitle.newChat, loaderData?.project?.name) }
  ]
}

export async function loader({ params }: Route.LoaderArgs) {
  const project = await api.getProject(params.projectId as string)
  return { project }
}

export default function ProjectNewSessionPage() {
  const { project } = useLoaderData<typeof loader>()
  return <ChatView project={project} sessionId={null} />
}
