import { Drawer } from 'antd'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router'
import { IconButton } from '~/components/common/IconButton'
import { Sidebar } from '~/components/layout/Sidebar'
import { api } from '~/lib/api'
import { recordLastAppRoute } from '~/lib/lastAppRoute'
import { PresenceProvider } from '~/lib/presenceContext'
import SidebarToggleIcon from '~/assets/icons/sidebar-toggle.svg?react'

const MD = '(min-width: 768px)'

// Sidebar data (projects + sessions) is loaded server-side so the shell paints
// with content on first render — no client-fetch flash. Revalidates on
// navigation, so newly created sessions/projects appear automatically.
export async function loader() {
  const [projects, sessions] = await Promise.all([
    api.listProjects(),
    api.listSessions()
  ])
  return { projects, sessions }
}

const matchesQuery = (q: string) =>
  typeof window !== 'undefined' && window.matchMedia(q).matches

export default function AppLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarDrawer, setSidebarDrawer] = useState(false)
  const location = useLocation()

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
          <Sidebar onNavigate={() => setSidebarDrawer(false)} />
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
