/* ================================================================
 * Static antd / @ant-design/x style extraction (zero-runtime baking)
 *
 * antd 6 runs on cssinjs: every component registers its style at RUNTIME.
 * With `theme.zeroRuntime = true` (see app/lib/msaTheme.ts) that runtime
 * registration is skipped entirely, so the styles have to exist as a real
 * CSS file — this script bakes it.
 *
 * How it stays in sync with the app:
 *   - the SAME theme config the app uses (`getMsaAntdTheme`), only with
 *     `zeroRuntime` flipped off, otherwise nothing would be generated;
 *   - `hashed: false` + an explicit `cssVar.key` per mode (in msaTheme) are
 *     what make the output deterministic: without them the selectors carry a
 *     token hash that differs between dev/prod builds and a `useId()`-derived
 *     css-var class that differs per render tree, and the baked file would
 *     stop matching the DOM;
 *   - `<StyleProvider layer>` mirrors root.tsx, so the output is wrapped in
 *     `@layer antd` / `@layer antdx`. Where those two layers RANK is not our
 *     business: this file ships no order statement, the app declares the
 *     authoritative `@layer …;` twice (app/app.css and root.tsx <head>) so the
 *     ranking survives any order the two are parsed in.
 *
 * Coverage: every uppercase export of `antd` and `@ant-design/x` is rendered
 * once per theme mode. Components that need props to mount get an entry in
 * the override maps below; anything that still throws is reported at the end
 * instead of failing the build (a missing exotic component costs styles for
 * that component only, and we never use most of them).
 *
 * A bare `<Comp />` is enough for a whole component: cssinjs registers the
 * component's entire style sheet in one go, so states and variants never need
 * to be acted out. The overrides only exist for two reasons — the component
 * throws without props, or a SUB-component owns a separate prefixCls and
 * therefore a separate style hook (`Space.Addon`, `Modal`'s pure panels,
 * `message`/`notification` panels), which the parent render cannot reach.
 *
 * Verifying coverage: `assertCoverage` does this on every run — it collects
 * every `getPrefixCls('…')` literal in antd/x and fails the build if one of them
 * never appears as `.ant-…` in the output, which is exactly what a style hook
 * we forgot to reach looks like.
 *
 * Run: `pnpm gen:antd-css` (wired into `pnpm dev` / `pnpm build`).
 * ================================================================ */
import { createCache, extractStyle, StyleProvider } from '@ant-design/cssinjs'
import * as x from '@ant-design/x'
import * as antd from 'antd'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import type { ReactNode } from 'react'
import { renderToString } from 'react-dom/server'
import { getMsaAntdTheme, MSA_ANTD_THEME_MODES } from '../app/lib/msaTheme'

type AnyComp = any

const require_ = createRequire(import.meta.url)
const sha8 = (input: string) =>
  createHash('sha256').update(input).digest('hex').slice(0, 8)

/** Files whose content decides what this script emits. Their hashes ride along
 * in the manifest so a dev server can tell it is serving a stale bake
 * (`app/lib/antdStyle.server.ts` compares them). app/app.css is deliberately
 * NOT here: it declares the layer ORDER (as does root.tsx) but contributes
 * nothing this output depends on — the emitted `@layer antd{…}` blocks name
 * their layer without ranking it. */
const BAKE_INPUTS = [
  'scripts/genAntdCss.tsx',
  'app/lib/msaTheme.ts',
  'app/lib/designTokens.ts'
]

/** Prefixes antd builds from a variable instead of a string literal, so the
 * scan below cannot see them (`float-btn` comes from `floatButtonPrefixCls`). */
const EXTRA_PREFIXES = ['float-btn']
/** Prefixes that own no style hook, i.e. legitimately absent from the output.
 * Empty today; an antd upgrade introducing one belongs here, next to a note on
 * why it carries no CSS. */
const STYLELESS_PREFIXES = new Set<string>()

/** `antd` exports that must not be rendered on their own. */
const ANTD_SKIP = new Set(['ConfigProvider', 'Grid', 'theme', 'version'])
// Nothing is skipped for being deprecated: `List` logs a deprecation warning on
// every render, and that warning showing up in this script's output is expected
// — the app does not use `List`, but dropping it would silently strip
// `.ant-list-*` from a file that is meant to be complete.
/** `@ant-design/x` exports that must not be rendered on their own
 * (`notification` here is the imperative XNotification API, not a panel). */
const X_SKIP = new Set(['XProvider', 'notification', 'version'])

/** Components whose bare `<Comp />` either throws or renders no style node. */
const ANTD_OVERRIDES: Record<string, (Comp: AnyComp) => ReactNode> = {
  Affix: (Affix) => (
    <Affix>
      <div />
    </Affix>
  ),
  // No BackTop entry on purpose: antd 6 still exports the legacy component,
  // which owns the `back-top` prefix and its own style hook, so it has to be
  // rendered as itself. `FloatButton.BackTop` shares `float-btn` with
  // `<FloatButton />` and is covered by that.
  Badge: (Badge) => (
    <>
      <Badge />
      <Badge.Ribbon />
    </>
  ),
  Cascader: (Cascader) => (
    <>
      <Cascader />
      <Cascader.Panel />
    </>
  ),
  Dropdown: (Dropdown) => (
    <Dropdown menu={{ items: [] }}>
      <div />
    </Dropdown>
  ),
  Popconfirm: (Popconfirm) => (
    <Popconfirm title="Confirm" open><button>Action</button></Popconfirm>
  ),
  Input: (Input) => (
    <>
      <Input />
      <Input.Search />
      <Input.TextArea />
      <Input.Password />
      <Input.OTP />
    </>
  ),
  Layout: (Layout) => (
    <Layout>
      <Layout.Header />
      <Layout.Sider />
      <Layout.Content />
      <Layout.Footer />
    </Layout>
  ),
  Menu: (Menu) => <Menu items={[]} />,
  // The confirm dialogs `modal.confirm()` opens are a different style path
  // than a plain <Modal>, and they are the ones the app uses most.
  Modal: (Modal) => (
    <>
      <Modal />
      <Modal._InternalPanelDoNotUseOrYouWillBeFired />
      <Modal._InternalPanelDoNotUseOrYouWillBeFired type="confirm" />
    </>
  ),
  QRCode: (QRCode) => <QRCode value="https://ant.design" />,
  // `Space.Addon` is not part of the Space style hook — it resolves its own
  // `space-addon` prefix and pulls `space/style/addon`.
  Space: (Space) => (
    <>
      <Space />
      <Space.Compact>
        <antd.Button />
      </Space.Compact>
      <Space.Addon>1</Space.Addon>
    </>
  ),
  Tag: (Tag) => (
    <>
      <Tag color="blue">Tag</Tag>
      <Tag color="success">Tag</Tag>
    </>
  ),
  Tree: (Tree) => <Tree treeData={[]} />,
  // Toasts render through a portal at runtime; their panel is the only way to
  // reach the style hook from a server render.
  message: (message) => <message._InternalPanelDoNotUseOrYouWillBeFired />,
  notification: (notification) => (
    <notification._InternalPanelDoNotUseOrYouWillBeFired />
  )
}

const X_OVERRIDES: Record<string, (Comp: AnyComp) => ReactNode> = {
  Actions: (Actions) => <Actions items={[]} />,
  Bubble: (Bubble) => (
    <>
      <Bubble content="." />
      <Bubble.List items={[]} />
    </>
  ),
  CodeHighlighter: (CodeHighlighter) => (
    <CodeHighlighter>{'const a = 1'}</CodeHighlighter>
  ),
  Conversations: (Conversations) => <Conversations items={[]} />,
  FileCard: (FileCard) => <FileCard item={{ uid: '1', name: 'a.txt' }} />,
  Folder: (Folder) => <Folder treeData={[]} />,
  Mermaid: (Mermaid) => <Mermaid>{'graph TD;'}</Mermaid>,
  Prompts: (Prompts) => <Prompts items={[]} />,
  Sender: (Sender) => (
    <>
      <Sender />
      <Sender.Header />
    </>
  ),
  Sources: (Sources) => <Sources items={[]} />,
  Suggestion: (Suggestion) => (
    <Suggestion items={[]}>{() => <div />}</Suggestion>
  ),
  Think: (Think) => <Think content="." />,
  ThoughtChain: (ThoughtChain) => <ThoughtChain items={[]} />
}

interface RenderReport {
  rendered: string[]
  skipped: string[]
}

/** Render one export into `cache`, isolated so a throwing component (bad
 * props, browser-only API) costs only its own styles. */
function renderOne(
  name: string,
  node: ReactNode,
  mode: (typeof MSA_ANTD_THEME_MODES)[number],
  cache: ReturnType<typeof createCache>,
  report: RenderReport
) {
  try {
    renderToString(
      <StyleProvider cache={cache} layer>
        <antd.ConfigProvider
          theme={{ ...getMsaAntdTheme(mode), zeroRuntime: false }}
        >
          {node}
        </antd.ConfigProvider>
      </StyleProvider>
    )
    report.rendered.push(name)
  } catch {
    report.skipped.push(name)
  }
}

function renderLibrary(
  lib: Record<string, unknown>,
  skip: Set<string>,
  overrides: Record<string, (Comp: AnyComp) => ReactNode>,
  mode: (typeof MSA_ANTD_THEME_MODES)[number],
  cache: ReturnType<typeof createCache>,
  report: RenderReport
) {
  for (const name of Object.keys(lib)) {
    if (skip.has(name) || name.startsWith('__')) continue
    // Components are PascalCase; `message` / `notification` are the two
    // lowercase APIs that still own styles.
    const isComponent =
      name[0] === name[0].toUpperCase() ||
      ['message', 'notification'].includes(name)
    if (!isComponent) continue

    const Comp = lib[name] as AnyComp
    const override = overrides[name]
    renderOne(name, override ? override(Comp) : <Comp />, mode, cache, report)
  }
}

function generate() {
  const cache = createCache()
  const report: RenderReport = { rendered: [], skipped: [] }

  // Both modes: component rules are token-agnostic in cssVar mode (they read
  // `var(--msa-ant-*)`) and therefore extracted once, but each mode owns its
  // own variable block — `.msa-theme-light{…}` / `.msa-theme-dark{…}` — and
  // those only exist if we render under that mode.
  for (const mode of MSA_ANTD_THEME_MODES) {
    renderLibrary(antd, ANTD_SKIP, ANTD_OVERRIDES, mode, cache, report)
    renderLibrary(x, X_SKIP, X_OVERRIDES, mode, cache, report)
  }

  const css = extractStyle(cache, true)
  if (!css) throw new Error('extractStyle returned nothing — aborting')
  return { css, report }
}

const ROOT = path.resolve(import.meta.dirname, '..')

/** Every `.js` file shipped in a package's `lib/`. */
function libFiles(pkg: string): string[] {
  const dir = path.join(
    path.dirname(require_.resolve(`${pkg}/package.json`)),
    'lib'
  )
  const out: string[] = []
  const walk = (d: string) => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.js')) out.push(full)
    }
  }
  walk(dir)
  return out
}

/** Fail the build when a component prefix antd/x can produce has no rules in
 * the output. Substring matching is deliberate: `.ant-tree` also matches
 * `.ant-tree-node`, so this catches a whole missing style hook rather than
 * individual rules — which is the failure mode zeroRuntime makes silent. */
function assertCoverage(css: string) {
  const literal = /getPrefixCls\('([a-z0-9-]+)'/g
  const prefixes = new Set(EXTRA_PREFIXES)
  for (const pkg of ['antd', '@ant-design/x']) {
    for (const file of libFiles(pkg)) {
      const src = fs.readFileSync(file, 'utf8')
      for (const [, prefix] of src.matchAll(literal)) prefixes.add(prefix)
    }
  }

  const missing = [...prefixes]
    .filter((p) => !STYLELESS_PREFIXES.has(p) && !css.includes(`.ant-${p}`))
    .sort()
  if (missing.length) {
    throw new Error(
      `no styles baked for: ${missing.join(', ')}\n` +
        'Each of these is a component (or sub-component) whose style hook the ' +
        'render never reached. Give it an entry in ANTD_OVERRIDES / X_OVERRIDES ' +
        '— a sub-component with its own prefixCls needs rendering explicitly. ' +
        'If it genuinely has no CSS, add it to STYLELESS_PREFIXES.'
    )
  }
  return prefixes.size
}

/** The stylesheet goes to `public/assets/`, not a directory of its own, because
 * `/assets/*` is the one prefix served as `immutable, max-age=1y`
 * (`frontend/server.js`, and `react-router-serve` before it) — everything else
 * out of the built client gets a short TTL instead, and a render-blocking sheet
 * whose filename already carries a content hash has no business being
 * revalidated on every page load.
 *
 * The manifest stays out of that directory: its name is stable, so a year-long
 * immutable cache is precisely what it must never be served with. */
const CSS_DIR = 'public/assets'
const MANIFEST_DIR = 'public/antd'

function write(css: string) {
  const cssDir = path.resolve(ROOT, CSS_DIR)
  const manifestDir = path.resolve(ROOT, MANIFEST_DIR)
  const content = `/* AUTO-GENERATED by scripts/genAntdCss.tsx — do not edit, do not commit. */\n${css}\n`
  const hash = sha8(content)
  const file = `antd.${hash}.css`

  fs.mkdirSync(cssDir, { recursive: true })
  fs.mkdirSync(manifestDir, { recursive: true })
  // Drop previous bakes so the served directories never accumulate stale
  // hashes; only this script's own output pattern is touched. The manifest
  // directory is swept unconditionally — an earlier layout kept the stylesheet
  // there, and a leftover copy would be served forever under a path nothing
  // points at (even one whose hash matches the current bake).
  for (const [dir, keep] of [
    [cssDir, file],
    [manifestDir, null]
  ] as const) {
    for (const entry of fs.readdirSync(dir)) {
      if (/^antd\.[0-9a-f]{8}\.css$/.test(entry) && entry !== keep) {
        fs.rmSync(path.join(dir, entry))
      }
    }
  }
  fs.writeFileSync(path.join(cssDir, file), content)
  fs.writeFileSync(
    path.join(manifestDir, 'manifest.json'),
    `${JSON.stringify(
      {
        href: `/assets/${file}`,
        hash,
        antd: antd.version,
        x: x.version,
        generatedAt: new Date().toISOString(),
        sources: Object.fromEntries(
          BAKE_INPUTS.map((rel) => [
            rel,
            sha8(fs.readFileSync(path.join(ROOT, rel), 'utf8'))
          ])
        )
      },
      null,
      2
    )}\n`
  )
  return { file, bytes: Buffer.byteLength(content) }
}

const { css, report } = generate()
const prefixes = assertCoverage(css)
const { file, bytes } = write(css)

console.log(
  `[gen:antd-css] ${file} — ${(bytes / 1024).toFixed(0)} kB, ` +
    `${report.rendered.length / MSA_ANTD_THEME_MODES.length} components, ` +
    `${prefixes} prefixes covered`
)
if (report.skipped.length) {
  console.warn(
    `[gen:antd-css] no style baked for: ${[...new Set(report.skipped)].join(', ')}`
  )
}
