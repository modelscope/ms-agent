import { Drawer } from 'antd'
import { useEffect, useRef, useState } from 'react'
import {
  Outlet,
  useLoaderData,
  useLocation,
  useNavigation,
  useRevalidator,
  type ShouldRevalidateFunctionArgs
} from 'react-router'
import { IconButton } from '~/components/common/IconButton'
import { Sidebar } from '~/components/layout/Sidebar'
import { api, orThrow } from '~/lib/api'
import { useOnMcpSkillChanged } from '~/lib/events'
import { recordLastAppRoute } from '~/lib/lastAppRoute'
import { useModelChanged } from '~/lib/modelChanged'
import { PresenceProvider } from '~/lib/presenceContext'
import SidebarToggleIcon from '~/assets/icons/sidebar-toggle.svg?react'

const MD = '(min-width: 768px)'

// Sidebar data (projects + sessions) is loaded server-side so the shell paints
// with content on first render — no client-fetch flash. Revalidates on
// navigation, so newly created sessions/projects appear automatically.
//
// The Composer's toolbar data rides along for the same reason: fetching it on
// mount made the pills paint placeholder labels first (the generic "Model") and
// then reflow
// to the real model name, visibly jolting the input box on every route change.
// Resolved here it is present in the first render, and React Router keeps the
// previous value while revalidating, so the row never changes width after paint.
//
// `searchSettings` is here for both reasons at once: it is GLOBAL config, so
// resolving it per Composer mount re-asked the same question on every session
// switch and flashed the "search not configured" pill in a beat late.
export async function loader() {
  // `orThrow` wraps the whole batch: any failure takes the app shell down, and
  // a raw ApiError loses its class and status across the SSR boundary.
  const [
    projects,
    sessions,
    providers,
    models,
    agentSettings,
    globalMcps,
    globalSkills,
    searchSettings
  ] = await orThrow(
    Promise.all([
      api.listProjects(),
      api.listSessions(),
      api.listProviders(),
      api.listModels(),
      api.getAgentSettings(),
      api.listMcps('global'),
      api.listSkills('global'),
      api.getSearchSettings()
    ])
  )

  return {
    projects,
    sessions,
    providers,
    models,
    agentSettings,
    globalMcps,
    globalSkills,
    searchSettings,
    // Identifies THIS run of the loader. `shouldRevalidate` below can refuse a
    // refresh the router had already committed to, so the layout needs to tell
    // "my data was reloaded" apart from "the reload was dropped" — see
    // `recoverInterruptedRefresh`. Compared for inequality only (server clock,
    // never rendered), so it costs no hydration risk.
    fetchedAt: Date.now()
  }
}

// Moving between sessions re-ran this whole loader — eight backend calls, six of
// which (providers/models/agentSettings/global MCPs/global skills/search) are
// GLOBAL config that navigating cannot possibly change. The scan behind
// `/api/skills` is the one that grows with the skills tree, so the waste also
// gets worse the more skills a user installs.
//
// Every mutation path already refreshes explicitly through `revalidator
// .revalidate()` (session create/rename/delete, model switches, and the
// presence heartbeat when a turn starts or ends), and those arrive with an
// unchanged URL — so honouring same-URL revalidations keeps the sidebar exactly
// as fresh as before while a pure route change now costs zero requests.
//
// Settings live OUTSIDE this layout, so returning from them remounts the route
// and runs the loader as an initial load (`shouldRevalidate` never applies) —
// edits made there are still picked up on the way back.
//
// Skipping route changes is only safe because a dropped refresh gets retried.
// React Router deliberately carries a pending revalidation into the navigation
// that interrupts it (its `isRevalidationRequired` forces `defaultShouldRevalidate`
// true) — but under single fetch that flag is indistinguishable from the `true`
// of an ordinary navigation, so this function cannot honour one without
// honouring all of them. Returning false therefore throws such a refresh away,
// and the router clears its flag on arrival: nothing tries again.
// `recoverInterruptedRefresh` in the component below closes that hole.
export function shouldRevalidate({
  currentUrl,
  nextUrl,
  formMethod,
  defaultShouldRevalidate
}: ShouldRevalidateFunctionArgs) {
  // A submission's result may well have changed this data — never skip those.
  if (formMethod && formMethod.toUpperCase() !== 'GET') {
    return defaultShouldRevalidate
  }
  // Same URL = an explicit `revalidate()` (or a fetcher settling), not a
  // navigation: this is the channel every mutation above uses, so let it pass.
  if (currentUrl.href === nextUrl.href) return defaultShouldRevalidate
  return false
}

const matchesQuery = (q: string) =>
  typeof window !== 'undefined' && window.matchMedia(q).matches

export default function AppLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarDrawer, setSidebarDrawer] = useState(false)
  const location = useLocation()

  // Global MCPs/skills come from this loader, and `shouldRevalidate` above
  // refuses to re-run on a route change — so a mutation has to say so, exactly
  // like session/model edits already do. Composer refreshes its own state on
  // this same event, but that only fixes the instance that is mounted: it is
  // rendered per route (ChatView, ProjectOverviewView), so the next one seeds
  // from this loader again and would snap back to the pre-edit list.
  //
  // `agentSettings` needs the same treatment: opening a session restores the
  // model it was held with by PUTting the global setting
  // (`useRestoreSessionModel`), which leaves the snapshot naming a model the
  // next turn will NOT run on — a pill that disagrees with the backend.
  //
  // Passed by reference, not wrapped: the hooks re-register their listeners
  // whenever the callback identity changes.
  const revalidator = useRevalidator()
  const { revalidate } = revalidator
  useOnMcpSkillChanged(revalidate)
  useModelChanged(revalidate)

  // Every channel above reaches this loader through `revalidate()`, and any of
  // them can lose its refresh to a navigation landing mid-flight (rename then
  // click away; `done` arriving as the user leaves) — see `shouldRevalidate`.
  // The worst case does not self-heal: the presence heartbeat only revalidates
  // on a CHANGED running set and commits the new set BEFORE asking, so a
  // dropped beat is a transition that never comes back and the unread dot it
  // was carrying is lost for good.
  //
  // Hence the stamp: a revalidation that ran without advancing `fetchedAt` was
  // dropped, so ask once more. Waiting for an idle router is required rather
  // than careful — `revalidate()` during a navigation re-runs the PENDING
  // location instead of the current one, which `shouldRevalidate` then refuses,
  // so a retry sent too early would discard itself.
  const { fetchedAt } = useLoaderData<typeof loader>()
  const navigation = useNavigation()
  const seenStampRef = useRef(fetchedAt)
  const askedRef = useRef(false)
  const retriedRef = useRef(false)
  useEffect(function recoverInterruptedRefresh() {
    if (revalidator.state === 'loading') {
      askedRef.current = true
      return
    }
    if (navigation.state !== 'idle') return
    if (fetchedAt !== seenStampRef.current) {
      seenStampRef.current = fetchedAt
      askedRef.current = false
      retriedRef.current = false
      return
    }
    if (!askedRef.current || retriedRef.current) return
    // One attempt per dropped refresh: whatever keeps the stamp from advancing
    // must cost a single extra request, never a loop.
    retriedRef.current = true
    revalidate()
  }, [revalidator.state, navigation.state, fetchedAt, revalidate])

  // Stash the current non-settings location so /settings → Back can jump
  // straight here instead of through the settings sub-nav history.
  useEffect(() => {
    recordLastAppRoute(location.pathname + location.search)
  }, [location.pathname, location.search])

  const toggleSidebar = () => {
    if (matchesQuery(MD)) setSidebarCollapsed((p) => !p)
    else setSidebarDrawer((p) => !p)
  }

  return (
    <PresenceProvider>
      <div className="flex h-screen bg-[var(--msa-bg-2)]">
        {/* Desktop sidebar (collapsible to compact icon-only mode) */}
        <div
          className={`hidden shrink-0 overflow-hidden transition-[width] duration-200 ease-out md:flex ${
            sidebarCollapsed ? 'md:w-[72px]' : 'md:w-72'
          }`}
        >
          <Sidebar
            collapsed={sidebarCollapsed}
            onCollapse={() => setSidebarCollapsed(true)}
            onExpand={() => setSidebarCollapsed(false)}
          />
        </div>

        {/* Mobile drawer */}
        <Drawer
          open={sidebarDrawer}
          onClose={() => setSidebarDrawer(false)}
          placement="left"
          size={288}
          closable={false}
          styles={{ body: { padding: 0 } }}
        >
          {/* The sidebar's own logo/collapse toggle must CLOSE the drawer here:
              there is no compact mode on small screens, and leaving
              `onCollapse` unset made that button inert (it renders and reacts to
              hover, but clicking did nothing). */}
          <Sidebar
            onCollapse={() => setSidebarDrawer(false)}
            onNavigate={() => setSidebarDrawer(false)}
          />
        </Drawer>

        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-[10px]">
          {/* Mobile sidebar toggle — opens the drawer (small screens only) */}
          <IconButton
            variant="filled"
            size="lg"
            onClick={toggleSidebar}
            icon={<SidebarToggleIcon className="h-6 w-6 rotate-180" />}
            className="absolute left-3 top-3 z-10 rounded-lg md:hidden"
          />

          <Outlet />
        </main>
      </div>
    </PresenceProvider>
  )
}
