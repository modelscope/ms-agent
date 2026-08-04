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
  return <ChatView project={null} sessionId={null} />
}
