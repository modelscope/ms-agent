import { useMemo } from 'react'
import { useLoaderData } from 'react-router'
import { ChatView } from '~/components/chat/ChatView'
import { ApiError, api, orThrow } from '~/lib/api'
import { historyToAgentMessages } from '~/lib/agentProvider'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/project-session'

/** "<session title> · <project> · <brand>" — falls back to the generic
 * "session" label when the turn hasn't been titled yet. */
export function meta({ loaderData, matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [
    {
      title: pageTitle(
        t,
        loaderData?.session?.title || t.pageTitle.session,
        loaderData?.project?.name
      )
    }
  ]
}

export async function loader({ params }: Route.LoaderArgs) {
  const sessionId = params.sessionId as string
  const [project, session, messages, plan, artifacts] = await Promise.all([
    // An unknown project id must surface as a 404 page, not "unexpected error".
    orThrow(api.getProject(params.projectId as string)),
    // Whether a turn is in flight (running in the background): drives an
    // immediate live re-attach instead of a blank assistant area.
    //
    // A 404 here means the URL names a session that does not exist — there is no
    // conversation to show, so it becomes the 404 page rather than an empty one.
    // Any OTHER failure stays best-effort: a transient blip must not replace a
    // readable session with an error page.
    api.getSession(sessionId, { silent: true }).catch((err) => {
      if (err instanceof ApiError && err.status === 404)
        throw new Response(err.message, { status: 404 })
      return null
    }),
    // History echo is best-effort: a fresh/unknown session yields an empty list
    // rather than blocking the page.
    api.listSessionMessages(sessionId, { silent: true }).catch(() => []),
    // Plan is best-effort too: resolved here so the pinned plan box renders in
    // the SSR first paint instead of flickering in after a client fetch.
    api.getSessionPlan(sessionId, { silent: true }).catch(() => null),
    // Same for the session's artifact ledger (composer file list) — without
    // it the "file list" row pops in after a client fetch on every reload.
    api.listArtifacts(sessionId).catch(() => [])
  ])
  return {
    project,
    session,
    sessionId,
    messages,
    plan,
    artifacts,
    running: !!session?.running
  }
}

export default function ProjectSessionPage() {
  const { project, sessionId, messages, plan, artifacts, running } =
    useLoaderData<typeof loader>()
  const initialMessages = useMemo(
    () => historyToAgentMessages(messages),
    [messages]
  )
  return (
    <ChatView
      project={project}
      sessionId={sessionId}
      initialMessages={initialMessages}
      initialPlan={plan}
      initialArtifacts={artifacts}
      initialRunning={running}
    />
  )
}
