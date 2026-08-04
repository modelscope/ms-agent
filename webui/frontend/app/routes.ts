import {
  type RouteConfig,
  index,
  layout,
  route
} from '@react-router/dev/routes'

export default [
  // Main app shell — sidebar + chat surfaces.
  layout('layouts/app.tsx', [
    index('routes/home.tsx'),
    route('projects/:projectId', 'routes/project-detail.tsx'),
    route('projects/:projectId/new', 'routes/project-new-session.tsx'),
    route(
      'projects/:projectId/sessions/:sessionId',
      'routes/project-session.tsx'
    )
  ]),

  // Settings — full-screen takeover (no app sidebar). Back button returns
  // the user to whatever they came from.
  route('settings', 'layouts/settings.tsx', [
    index('routes/settings/index.tsx'),
    route('models', 'routes/settings/models.tsx'),
    route('mcp-skills', 'routes/settings/mcp-skills.tsx'),
    route('personalization', 'routes/settings/personalization.tsx'),
    route('appearance', 'routes/settings/appearance.tsx')
  ]),

  // Unmatched URLs go straight to the home page (loader redirect) — the app
  // has no redirect-only routes for valid destinations.
  route('*', 'routes/catch-all.tsx')
] satisfies RouteConfig
