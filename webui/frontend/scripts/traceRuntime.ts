/**
 * Assemble `build-runtime/` — the exact tree the production image runs.
 *
 * It holds the build output, `server.js`, `package.json`, and ONLY the
 * `node_modules` files reachable from the two entries Node actually loads in
 * production: `build/server/index.js` (the SSR bundle) and `server.js`. The
 * image used to ship `pnpm prune --prod`'s whole tree, 430 MB, because Vite
 * leaves SSR dependencies external and they therefore have to exist at runtime.
 * Almost none of those bytes are reachable, though — the waste is INSIDE the
 * packages, not a list of packages nobody asked for: antd ships 58 MB of `es/`
 * plus `lib/` plus every locale, of which SSR touches 2.3 MB; mermaid 75 MB of
 * which 2.3 MB; `typescript` (24 MB) is only a peer of `@react-router/node` and
 * is never imported. Tracing the real closure instead lands around 51 MB.
 *
 * `@vercel/nft` does the tracing (the same resolver Vercel packages functions
 * with), so `require`/`import`/`import()` with a static specifier, subpath
 * exports and pnpm's symlink layout are all handled. What it CANNOT see is a
 * specifier computed at runtime, and a package missing for that reason would
 * surface as a 500 on whichever page needs it. Hence `verify()`: this script
 * boots the assembled tree and renders a page through it before returning, so
 * that failure lands on whoever builds the image instead of on a user.
 *
 * Not part of `pnpm build`: it costs a copy of ~50 MB and 17s of tracing, and
 * only the image consumes it. `pnpm build:image` is `pnpm build` plus this, and
 * it is what the Dockerfile's frontend stage runs.
 */
import { nodeFileTrace } from '@vercel/nft'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'

const root = process.cwd()
const out = path.join(root, 'build-runtime')

/** What Node loads at runtime. `server.js` is the process entry; it imports the
 *  SSR bundle dynamically (`await import(SERVER_BUILD.href)`) from a URL built
 *  at runtime, which is exactly the shape nft cannot follow — so the bundle is
 *  named here as a second entry rather than left to be discovered. */
const ENTRIES = ['build/server/index.js', 'server.js']

/** Copied whole, not traced: `build/client` is served to browsers as opaque
 *  files (nft has no reason to know they exist), and `package.json` is what
 *  makes Node read `server.js` as ESM — `"type": "module"` lives there. `public/`
 *  is deliberately absent, as it is from today's image: `react-router build`
 *  already copied it into `build/client`, and server.js's own fallback for it
 *  passes `fallthrough: true`, so a missing directory is a no-op. */
const VERBATIM = ['build', 'server.js', 'package.json']

/** Rendered by the smoke check. Chosen because it needs NO reachable backend:
 *  its loader degrades an API failure to empty lists (the project-wide
 *  convention), so the page still renders and a 200 means the whole antd +
 *  @ant-design/x + react-router import graph resolved and React ran. The home
 *  route would answer 500 here — it lets the API error through on purpose. */
const SMOKE_PATH = '/settings/mcp-skills'

const mb = (bytes: number): string => (bytes / 1024 / 1024).toFixed(1) + ' MB'

/** Distinct free loopback ports. Every probe is held open until the last one is
 *  bound, because the OS happily hands back a port it released a millisecond
 *  ago: probing them one at a time returned the SAME number twice, which aimed
 *  the app's API base at the port it was serving on and had server.js proxy
 *  `/api` to itself. */
function freePorts(count: number): Promise<number[]> {
  return new Promise((resolve, reject) => {
    const probes: net.Server[] = []
    const ports: number[] = []
    const next = (): void => {
      if (ports.length === count) {
        let pending = probes.length
        for (const probe of probes) probe.close(() => --pending || resolve(ports))
        return
      }
      const probe = net.createServer()
      probes.push(probe)
      probe.once('error', reject)
      probe.listen(0, '127.0.0.1', () => {
        ports.push((probe.address() as net.AddressInfo).port)
        next()
      })
    }
    next()
  })
}

function connects(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: '127.0.0.1' })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => {
      socket.destroy()
      resolve(false)
    })
  })
}

/** Boot the assembled tree and render one page through it. */
async function verify(): Promise<void> {
  // Two ports: one to serve on, one that is guaranteed to refuse connections so
  // the API is *reachably absent*. Pointing the app at a port something else
  // happens to hold would have it render whatever that answers.
  const [port, closed] = await freePorts(2)
  const child = spawn(process.execPath, ['./server.js'], {
    cwd: out,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      NODE_ENV: 'production',
      HOST: '127.0.0.1',
      PORT: String(port),
      MS_AGENT_API_BASE_URL: `http://127.0.0.1:${closed}`,
      MS_AGENT_FRONTEND_API_BASE_URL: `http://127.0.0.1:${closed}`,
      MS_AGENT_WEBUI_BANNER: '0'
    }
  })
  let log = ''
  child.stdout.on('data', (chunk: Buffer) => (log += chunk))
  child.stderr.on('data', (chunk: Buffer) => (log += chunk))
  let exited: number | null = null
  child.once('exit', (code) => (exited = code ?? 0))

  const fail = (message: string): never => {
    child.kill('SIGKILL')
    throw new Error(`${message}\n--- server output ---\n${log.trim()}`)
  }

  try {
    // Importing the SSR bundle takes a second or two before the socket is bound;
    // a container under load takes longer, so the budget is generous.
    const deadline = Date.now() + 60_000
    while (!(await connects(port))) {
      if (exited !== null) fail(`server.js exited with ${exited} before listening`)
      if (Date.now() > deadline) fail('server.js never accepted a connection')
      await new Promise((resolve) => setTimeout(resolve, 200))
    }

    const response = await fetch(`http://127.0.0.1:${port}${SMOKE_PATH}`)
    const body = await response.text()
    if (response.status === 404) {
      fail(`${SMOKE_PATH} is gone — point SMOKE_PATH at a route that renders without a backend`)
    }
    if (response.status !== 200) {
      fail(`${SMOKE_PATH} answered ${response.status}, expected 200`)
    }
    // A 200 carrying an empty shell would mean antd never rendered: this class
    // is the css-var key `getMsaAntdTheme()` pins, so it only appears once the
    // theme and the component tree actually made it into the HTML.
    if (!/msa-theme-(?:light|dark)/.test(body)) {
      fail(`${SMOKE_PATH} rendered without the antd theme class — the SSR output is not usable`)
    }
    // The two ways a dependency nft could not see reports itself.
    const missing = log.match(/Cannot find (?:package|module) [^\n]+/)
    if (missing) fail(`a dependency is missing from the traced tree: ${missing[0]}`)

    console.log(`[webui] Verified ${SMOKE_PATH} renders from build-runtime (${body.length} bytes)`)
  } finally {
    if (exited === null) {
      child.kill('SIGTERM')
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          child.kill('SIGKILL')
          resolve(null)
        }, 5_000)
        child.once('exit', () => {
          clearTimeout(timer)
          resolve(null)
        })
      })
    }
  }
}

for (const entry of ENTRIES) {
  if (!fs.existsSync(path.join(root, entry))) {
    throw new Error(`Missing ${entry} — run \`pnpm build\` first`)
  }
}

// Retries, because the default of none makes this a coin flip on macOS: a
// recursive remove scans a directory, unlinks what it saw, then rmdir's it, and
// Finder drops a `.DS_Store` into `build-runtime` the moment it is looked at —
// arriving after the scan, that turns the rmdir into ENOTEMPTY and fails the
// whole build on nothing. Node retries exactly this class when asked to.
fs.rmSync(out, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
for (const rel of VERBATIM) {
  fs.cpSync(path.join(root, rel), path.join(out, rel), { recursive: true })
}

const { fileList } = await nodeFileTrace(
  ENTRIES.map((rel) => path.join(root, rel)),
  { base: root }
)

let files = 0
let bytes = 0
for (const rel of fileList) {
  // Only dependencies: everything else the tree needs is in VERBATIM, and
  // leaving the rest out keeps stray sources (`app/`, `public/`) from riding
  // along just because something referenced their path.
  if (!rel.startsWith('node_modules/')) continue
  const src = path.join(root, rel)
  const dst = path.join(out, rel)
  fs.mkdirSync(path.dirname(dst), { recursive: true })
  // pnpm's layout is symlinks into `.pnpm/`, and nft lists both the link and
  // its target. Recreating the link (rather than following it) keeps the
  // resolution behaviour identical to the tree this was traced from — and keeps
  // one physical copy of a package shared by several dependents.
  const stat = fs.lstatSync(src)
  if (stat.isSymbolicLink()) {
    fs.symlinkSync(fs.readlinkSync(src), dst)
  } else if (stat.isFile()) {
    fs.copyFileSync(src, dst)
    bytes += stat.size
  }
  files += 1
}
if (files === 0) throw new Error('Traced no dependencies at all — the entries cannot be right')

await verify()

console.log(`[webui] build-runtime carries ${files} dependency entries, ${mb(bytes)}`)
