# WebUI development

MS-Agent WebUI provides a FastAPI API and a React Router frontend over the
MS-Agent SDK. User-facing installation and usage instructions are in `README.md` and
`README_ZH.md`. Commands below are relative to `webui/` unless stated otherwise.
The SDK command `ms-agent ui` prepares its environment and invokes the shared
launcher; its integration is in `../ms_agent/cli/ui.py`.

## Build and run

Use Python 3.12+, uv >=0.5, Node >=22.22.0 and pnpm 10.17.1.
Run each development server from its own terminal, starting at the WebUI root:

```bash
cd backend
uv sync --locked
uv run dev                 # API development server, loopback :8000
# In another terminal:
cd frontend
pnpm install --frozen-lockfile
pnpm dev                   # frontend development server, :5173
```

For the complete app, build with `pnpm build` in `frontend/`, then run
`uv run webui --no-open` in `backend/`. The common launcher supervises a
loopback API process and a Node SSR process; only one public URL is announced
after API, SSR and generated CSS respond correctly. Either process failing
stops both and returns a failure. Ctrl-C, SIGTERM and SIGHUP clean up the stack.
The default public port is the first available from 8000; an explicit `--port`
or `--backend-port` fails if busy. The launcher sets both
`MS_AGENT_API_BASE_URL` (proxy) and `MS_AGENT_FRONTEND_API_BASE_URL` (SSR).

`pnpm build` includes Ant Design CSS generation and records its inputs/outputs
in `build/webui-build.json`. Do not bypass it with a raw React Router build or
mix a new stylesheet with an older SSR bundle. `frontend/scripts/buildManifest.ts`
records the build, and `backend/app/frontend.py` validates it. Missing or stale
builds fail with a rebuild instruction.

`backend/pyproject.toml` uses the SDK checkout as an editable dependency.
Keep its dependencies aligned with the SDK's `requirements/webui.txt` and
`backend/uv.lock`; optional integrations must not become mandatory imports.
Package preparation and installed-wheel validation live in
`../.dev_scripts/webui/` and run from the SDK root.

**Backend configuration** is resolved relative to `backend/app/core/settings.py`,
not the command's working directory. Process variables take precedence over
`backend/.env`, then `webui/.env`, then the SDK root's `.env`. Installed-package
mode uses process variables and saved SDK settings, without searching for dotenv
files in cache or site-packages directories. Settings are declared in
`backend/.env.example`. The settings loader also exports dotenv values without
overwriting process variables, so SDK code and MCP `${VAR}` placeholders can use
them. Preserve this behavior across entry points.

`MS_AGENT_HOME` defaults to `~/.ms_agent` and controls SDK settings and managed
project data. A user-selected project workspace stays at its chosen location.
Do not implement a second storage or configuration layer in the WebUI.

**Tests** (from `backend/`): `uv run pytest`; real-model tests opt in with
`RUN_INTEGRATION=1 uv run pytest tests/integration` and suitable provider settings.
Install frontend dependencies first: launcher tests execute the TypeScript
build-manifest producer through `tsx`.

### Frontend (React Router v8 / Vite)

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev                 # http://localhost:5173, proxies /api/* to :8000
pnpm build               # production build
pnpm build:image         # the above, then assemble build-runtime/ — a traced runtime tree
pnpm start               # serve the build: SSR + /api proxy on one port (PORT, default: API port + 1)
```

**Runtime image build:** `pnpm build:image` runs the normal build, then
`scripts/traceRuntime.ts` traces the SSR entries with `@vercel/nft` into
`build-runtime/` and verifies the assembled tree with a smoke render.

`../docker/webui.Dockerfile` enables the same flow for installed packages with
`MS_AGENT_WEBUI_TRACE_RUNTIME=1`. The prepared cache records whether its runtime
is traced. To run the traced tree locally from `backend/`, use
`uv run webui --frontend-dir ../frontend/build-runtime`; the launcher rejects it
when its manifest does not match the checkout build.

**Frontend configuration** is declared in `backend/.env.example` and read by
application code through `frontend/app/lib/env.ts`. Its `SERVER_*` exports are
server-side values: the browser build replaces `process.env` with `{}`. Importing
one of those constants directly into a component can compile but give different
values during SSR and hydration. Send approved non-secret values through a loader
and read loader data in the component; `useHosted()` is the example to follow.
`env.ts` remains isomorphic because `api.ts` is shared by SSR and browser code.

- `pnpm dev` / `pnpm build`: Vite's `envDir` points to `backend/`, and the React
  Router plugin loads that dotenv configuration into the SSR process. Put values
  needed by the frontend in `backend/.env` or the process environment; Vite does
  not read the repository root's shared `.env` layer. Real process variables win.
- `pnpm start`: `server.js` does not load dotenv files; pass process variables.
  The launcher passes the resolved environment to its child processes. Provider
  secrets may be available to SSR, so reconsider that boundary if SSR is deployed
  separately. Never expose credentials via `VITE_*`, loader data or client bundles.
- In development, dotenv merging is additive: restart the dev server after
  changing **or removing** a variable that has already been loaded.
- Project-owned variables use `MS_AGENT_`; frontend settings use
  `MS_AGENT_FRONTEND_`. Third-party credential names stay verbatim for SDK/MCP
  compatibility. `HOST`/`PORT` remain unprefixed for production binding. Vite's
  development port is configured separately in `vite.config.ts`.

Two API addresses have distinct consumers and must point to the same backend:

| Variable | Consumer |
| --- | --- |
| `MS_AGENT_API_BASE_URL` | `server.js` production `/api` proxy |
| `MS_AGENT_FRONTEND_API_BASE_URL` | SSR requests through `app/lib/api.ts` and Vite's development proxy |

SSR loaders bypass the production proxy. If the API port changes, set both
addresses; otherwise browser requests and SSR can silently reach different
backends. Vite reads the value with `loadEnv` because its config runs before the
React Router plugin populates `process.env`.

`MS_AGENT_FRONTEND_HOSTED_MODE=1` hides controls for paths on the server, including
project location and directory-path skill import. The root loader passes this flag
to components through `useHosted()` in `app/lib/hosted.ts`; do not read it from
`import.meta.env` or import `SERVER_HOSTED_MODE` directly into a component.
This flag only changes the UI: the backend still accepts paths, so any required
access restriction must be enforced in the backend too.

### Type Check

```bash
cd frontend
pnpm typecheck           # runs react-router typegen + tsc --noEmit
```

## Tech Stack

| Layer    | Stack                                                                                                 |
| -------- | ----------------------------------------------------------------------------------------------------- |
| Frontend | React 19, React Router v8 (SSR), Tailwind CSS v4, Ant Design 6, @ant-design/x 2, Vite 8, TypeScript 6 |
| Backend  | Python 3.12, FastAPI, sse-starlette, pydantic-settings, managed by `uv`                               |
| Chat     | SSE streaming via `POST /api/chat`, events: `delta` / `done`                                          |
| i18n     | EN / 中文, via `app/lib/i18n.tsx` (`useT` hook), persisted in cookie                                  |

## Architecture

- **Frontend entry**: `frontend/app/root.tsx` → layouts (`app.tsx`, `settings.tsx`) → routes
- **Chat system**: `@ant-design/x-sdk` (`useXChat`, `XRequest`) + custom `AgentChatProvider` in `app/lib/agentProvider.ts`
- **Design tokens**: Defined in `app/lib/designTokens.ts`, consumed via CSS variables (`--msa-*`), applied through Tailwind (`text-msa-text-1`, `bg-msa-fill-2`, etc.)
- **Backend**: `backend/app/api/` handles HTTP requests and response envelopes;
  `backend/app/backends/ms_agent/` adapts SDK projects, sessions, chat, models,
  skills, MCP, memory and files. Management routes call adapters directly; chat
  streams through `get_backend().chat_stream`. Execution and persistence belong
  in SDK services, not duplicated interface code.
- **Contracts**: update backend models, `frontend/app/lib/types.ts` and
  `frontend/app/lib/agentProvider.ts` together when changing event payloads.
  Preserve frame order, identifiers and completion handling. In-memory session
  runtime requires one API worker; shutdown must close owned SDK resources and
  file watchers.
- **State lifecycle**: `bootstrap.py` initializes SDK project/session storage
  before normal API operations become available. Missing default project metadata
  opens the recovery page; only health and recovery endpoints remain available
  until an explicitly confirmed backup, repair and initialization succeed.
  Request handlers use `common.pm()` and
  `common.sm_for()` without implicit entity creation. Protect the complete
  read-modify-write operation with the SDK file lock; keep network calls and
  async waits outside it. Acquire project storage, settings, then sidecar locks
  in that order when an operation needs more than one.
- **Conversation models**: `session_models.py` saves selections and prepares
  each turn's model configuration. An explicit selection updates the session
  and the new-chat default; restoring or sending an existing session does not
  change that default. Drafts stay in page state until creation. Frontend
  settings requests must send only fields the user changed.
- **SSR + antd**: antd/x run with `theme.zeroRuntime`, so no component CSS is generated at request time. `pnpm gen:antd-css` (auto-run by `pnpm dev` / `pnpm build`) renders every antd + `@ant-design/x` component through `scripts/genAntdCss.tsx` into `public/assets/antd.<hash>.css`; the root loader returns its href via `app/lib/antdStyle.server.ts` and `root.tsx` links it in `<head>`. `entry.server.tsx` therefore streams HTML untouched.

`frontend/server.js` must route `/api/*` before compression and the SSR catch-all.
Stream SSE without buffering, compression or a read timeout that cuts off long
turns. Preserve forwarded client headers, remove hop-by-hop headers, and keep the
request body limit for both declared-length and streamed uploads. A raw
`react-router-serve` process does not provide this API proxy.

## Code Conventions

### Antd static methods

**Never** import and call `message`, `Modal`, `notification` directly. Always obtain them through `App.useApp()` hooks to inherit `ConfigProvider` theme.

```tsx
// ✗ Wrong
import { message } from 'antd'
message.success('done')

// ✓ Correct
import { App } from 'antd'
const { message, modal, notification } = App.useApp()
message.success('done')
```

### Antd theme and generated CSS

antd runs zero-runtime (see Architecture above): component CSS exists **only** in the file baked by `pnpm gen:antd-css`, keyed by the css-var class `msa-theme-light` / `msa-theme-dark` that `getMsaAntdTheme()` pins.

- **Never** wrap a subtree in `<ConfigProvider theme={{…}}>`. antd derives that subtree's css-var key from `useId()`, so its variables cannot be baked and the subtree renders with unresolved `var(--msa-ant-*)` until hydration.
- Component token tweaks go into the `components` maps in `app/lib/msaTheme.ts` (both light and dark), or into component-scoped CSS (below).
- After changing `msaTheme.ts`, re-run `pnpm gen:antd-css` in development (or
  restart `pnpm dev`). Production builds must use the complete `pnpm build`
  pipeline so CSS, SSR, client files and `build/webui-build.json` agree.
- When introducing an Ant Design or `@ant-design/x` component, ensure
  `scripts/genAntdCss.tsx` renders it and the variants that need CSS. A successful
  page render does not prove its component styles were generated.

### Design tokens

- All colors, borders, backgrounds must use project design tokens (e.g. `bg-msa-fill-2`, `text-msa-text-1`, `border-msa-line-1`, `rounded-xl`).
- **No** hardcoded color values (hex, rgb, slate-\*, etc.).
- For antd component style overrides, prefer the component's `classNames` prop over arbitrary variant selectors.

### Component-scoped CSS for Antd internals

When you need to target antd internal DOM nodes (e.g. `.ant-tabs-content`, `.ant-tree-title`) that cannot be reached via `classNames` prop:

1. **Do NOT** use Tailwind arbitrary variants like `[&_.ant-tabs-content]:h-full` — they are unreliable in Tailwind v4.
2. **Create a co-located CSS file** next to the component (e.g. `MyComponent.css`) and import it in the component.
3. **Use a component-level class prefix** to avoid style collisions. The prefix should be a short abbreviation of the component name:
   - `ProjectOverviewView` → `pov-`
   - `SessionRightRail` → `srr-`
   - `mcp-skills` route → `mcp-skills-`
4. Example:
   ```css
   /* ProjectOverviewView.css */
   .pov-tabs-scroll .ant-tabs-content {
     height: 100%;
     overflow-y: auto;
   }
   ```
   ```tsx
   import './ProjectOverviewView.css'
   ;<Tabs className="pov-tabs-scroll" />
   ```

### SVG icons

SVG icon assets in `app/assets/icons/` use `currentColor` for painted fills and
strokes so CSS controls their color; preserve `none` where no paint is intended.
Import with the `?react` suffix (`import Icon from '~/assets/icons/foo.svg?react'`).

### i18n

All user-visible text must go through `useT()` (`t.namespace.key`). When adding new keys, update:

1. `frontend/app/lib/locales/en.json`
2. `frontend/app/lib/locales/zh.json`

`Dict` is derived from the English JSON, and Chinese must match its structure;
there is no separate interface to maintain. Language is persisted in a cookie
and passed into SSR; preserve the same initial language through hydration.

### Interaction patterns

- **Delete actions** must always be wrapped with `Popconfirm` for confirmation. The confirm title should dynamically include the item type and name.
- **Popconfirm** should wrap the trigger button (e.g. the "more" dropdown button), not the entire card/row.
- **Icon-only buttons** must have a `Tooltip` with an i18n label.

### Cross-component data sync

When a component **mutates data that other mounted components display** (e.g. workspace files uploaded via a modal while a workspace panel is open), it must notify those consumers so they refresh. Use the lightweight event bus in `app/lib/events.ts`:

1. **Producer** (the component performing the mutation): call the dispatch helper after the operation succeeds.
   ```ts
   import { dispatchWorkspaceChanged } from '~/lib/events'
   await Promise.all(uploads)
   dispatchWorkspaceChanged()
   ```
2. **Consumer** (the component displaying the data): subscribe with the corresponding hook.
   ```ts
   import { useOnWorkspaceChanged } from '~/lib/events'
   useOnWorkspaceChanged(loadFiles) // re-fetches file list
   ```

Current event definitions live in `app/lib/events.ts`:

| Event | Purpose |
| --- | --- |
| `msa:urlchange` | Refresh URL-dependent UI after `history.replaceState` |
| `msa:workspace-changed` | Refresh workspace data; optional `created` paths support immediate updates |
| `msa:mcp-skill-changed` | Refresh MCP/skill lists and composer counts |
| `msa:session-started` / `msa:session-done` | Update running indicators; detail is the session ID |
| `msa:project-settings-changed` | Refresh widgets after project settings are saved |

For a new cross-component update, add a `dispatch*` / `useOn*` pair in `events.ts`,
keep the `msa:` namespace and document the payload at its definition. Subscribers
must remove listeners on cleanup.
