import { useLocation } from 'react-router'
import { ChatView } from '~/components/chat/ChatView'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/home'

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [
    { title: pageTitle(t, t.pageTitle.newChat) },
    { name: 'description', content: t.chat.welcomeDesc }
  ]
}

export default function Home() {
  // Keyed on `location.key` for the same reason as the project "new chat" route:
  // sending the first message rewrites the address bar to /sessions/<id> via
  // `history.replaceState` (no router navigation, so the stream survives), which
  // leaves the router believing it is still on "/". Clicking "new chat" then
  // navigates to "/" — same pathname, component reused, old conversation still
  // on screen. A fresh `location.key` per navigation remounts it clean.
  const location = useLocation()
  return <ChatView key={location.key} project={null} sessionId={null} />
}
