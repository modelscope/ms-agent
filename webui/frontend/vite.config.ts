import { reactRouter } from '@react-router/dev/vite'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import svgr from 'vite-plugin-svgr'

export default defineConfig(({ mode }) => {
  // Read the adjacent backend's dotenv file for shared application settings.
  // The backend additionally reads a shared layer one level further up
  // (`<repo>/.env`, see `backend/app/core/settings.py`) which this does NOT look
  // at -- put anything the frontend needs in `backend/.env` itself, under an
  // `MS_AGENT_FRONTEND_` prefix: `MS_AGENT_` keeps every key this project owns out
  // of the way of whatever else the shell has set, and `FRONTEND_` says which side
  // owns it. Third-party names stay verbatim by necessity (`OPENAI_API_KEY`,
  // `EXA_API_KEY`, ...): the backend republishes them to `os.environ` for the SDK
  // and for `mcp.json` `${VAR}` placeholders, which match them literally.
  //
  // Inheriting the backend's keys wholesale is safe on both counts that matter:
  //   - HOST / PORT do not collide. They land in `process.env` but nothing here
  //     consumes them: vite takes `server.port` from the config below, and the
  //     production entry (`server.js`, `pnpm start`) never runs vite, so it never
  //     reads this file at all. Verified with `PORT=8000 HOST=0.0.0.0 pnpm dev`,
  //     which still served 5173.
  //   - Provider credentials cannot reach the browser. Only `VITE_`-prefixed keys
  //     are exposed to client code, and vite refuses to let that prefix be
  //     widened to ''. They do enter the SSR process's `process.env`; that is
  //     acceptable while both processes run on the same host, and is the thing to
  //     revisit if the frontend is ever deployed apart from the backend.
  const envDir = fileURLToPath(new URL('../backend/', import.meta.url))

  // Read with `loadEnv` here rather than off `process.env`: `@react-router/dev`
  // merges this same file into `process.env` from its plugin's `config` hook,
  // which runs AFTER this module is evaluated. Reading `process.env` directly
  // would honour `MS_AGENT_FRONTEND_API_BASE_URL` for loaders (via `api.ts`, per
  // request) while silently ignoring it for this proxy -- sending SSR and the
  // browser to two different backends. Empty prefix = every key; a real
  // environment variable still wins, since `loadEnv` lets `process.env` overwrite
  // the file's values.
  const apiBaseUrl =
    loadEnv(mode, envDir, '').MS_AGENT_FRONTEND_API_BASE_URL ||
    'http://127.0.0.1:8000'

  return {
    envDir,
    plugins: [svgr(), tailwindcss(), reactRouter()],
    resolve: {
      alias: {
        '~': fileURLToPath(new URL('./app', import.meta.url))
      }
    },
    server: {
      port: 5173,
      proxy: {
        // Preserve the browser's Host for the backend's same-origin check,
        // including when Vite selects a different available development port.
        '/api': { target: apiBaseUrl, changeOrigin: false }
      }
    },
    ssr: {
      // x-markdown's es/ build imports CSS, which Node can't load; route it
      // through Vite so its CSS pipeline handles it. Regex (not a bare package
      // name) so DEEP imports like `plugins/Latex` (no `exports` map) match too.
      // NOTE: katex itself must stay external — its UMD build breaks under
      // Vite's strict-mode SSR transform ("Cannot set properties of undefined").
      noExternal: [/@ant-design\/x-markdown/]
    }
  }
})
