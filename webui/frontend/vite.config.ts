import { reactRouter } from '@react-router/dev/vite'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import svgr from 'vite-plugin-svgr'

const apiBaseUrl = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [svgr(), tailwindcss(), reactRouter()],
  resolve: {
    // Array form with ANCHORED regex finds: a bare string alias is a prefix
    // match, so '@ant-design/x-markdown' would also mangle subpath imports
    // (themes/dark.css → es/index.js/themes/dark.css, "duplicated modules"
    // warning). Anchors rewrite only the exact ids we mean.
    alias: [
      {
        find: '~',
        replacement: fileURLToPath(new URL('./app', import.meta.url))
      },
      // x-markdown's lib/ (CJS) does `require("./*.css")` which Node can't
      // parse. Force the es/ entry so Vite's CSS pipeline handles it.
      {
        find: /^@ant-design\/x-markdown$/,
        replacement: '@ant-design/x-markdown/es/index.js'
      }
    ]
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiBaseUrl, changeOrigin: true }
    }
  },
  ssr: {
    // Prefer CJS (lib/) for Node SSR so antd's es/ extensionless imports
    // don't fail under strict Node ESM resolution.
    resolve: {
      mainFields: ['main', 'module'],
      conditions: ['node', 'require'],
      externalConditions: ['node', 'require']
    },
    // x-markdown's lib/ build contains syntax Node SSR can't parse; route it
    // through Vite so esbuild handles the transform. Regex (not a bare package
    // name) so DEEP imports like `plugins/Latex` (no `exports` map) match too.
    // NOTE: katex itself must stay external — its UMD build breaks under
    // Vite's strict-mode SSR transform ("Cannot set properties of undefined").
    noExternal: [/@ant-design\/x-markdown/]
  }
})
