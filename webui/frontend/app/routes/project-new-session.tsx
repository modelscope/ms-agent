import { useLoaderData, useLocation } from 'react-router'
import { ChatView } from '~/components/chat/ChatView'
import { api, orThrow } from '~/lib/api'
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
  // An unknown project id must surface as a 404 page, not "unexpected error".
  const project = await orThrow(api.getProject(params.projectId as string))
  return { project }
}

export default function ProjectNewSessionPage() {
  const { project } = useLoaderData<typeof loader>()
  // Keyed on `location.key` so hitting "new chat" while ALREADY on this route
  // starts a genuinely empty chat.
  //
  // Once the first message is sent, ChatPanel swaps the address bar to
  // /sessions/<id> with `history.replaceState` — deliberately not a router
  // navigation, so the stream isn't cut. The router therefore still considers
  // itself on /new. A later "new chat" click navigates to the same pathname, so
  // this component is reused and kept its finished conversation on screen — the
  // button looked dead. A same-path navigation does mint a fresh `location.key`
  // (unlike the pathname), which remounts ChatView and clears that state.
  const location = useLocation()
  return (
    <ChatView key={location.key} project={project} sessionId={null} />
  )
}
