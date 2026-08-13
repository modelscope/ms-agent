/**
 * File extension → Monaco language id.
 *
 * Single source of truth for every editor/preview surface (workspace rail,
 * skill viewer, …) — the mapping used to be duplicated per component, which let
 * the two drift (one knew `markdown`/`xml`, the other didn't).
 *
 * Ids are only listed when monaco actually ships a tokenizer for them
 * (`monaco-editor/esm/vs/basic-languages/*`), so every entry here yields real
 * syntax highlighting. A handful additionally get a full language service
 * (diagnostics/completion) via a dedicated worker — see CodeEditor's
 * MonacoEnvironment: json, css/scss/less, html/handlebars/razor, and
 * typescript/javascript. Everything else is highlighting + the generic editor
 * worker, which is all monaco offers for those languages.
 */
const LANGUAGE_BY_EXT: Record<string, string> = {
  // --- with a dedicated language service (worker) ---
  json: 'json',
  jsonc: 'json',
  json5: 'json',
  css: 'css',
  scss: 'scss',
  less: 'less',
  html: 'html',
  htm: 'html',
  hbs: 'handlebars',
  handlebars: 'handlebars',
  ts: 'typescript',
  mts: 'typescript',
  cts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  jsx: 'javascript',

  // --- syntax highlighting only (no upstream worker exists) ---
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'mdx',
  py: 'python',
  pyi: 'python',
  go: 'go',
  rs: 'rust',
  java: 'java',
  kt: 'kotlin',
  kts: 'kotlin',
  swift: 'swift',
  rb: 'ruby',
  php: 'php',
  cs: 'csharp',
  c: 'cpp',
  h: 'cpp',
  cc: 'cpp',
  cpp: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  hh: 'cpp',
  m: 'objective-c',
  mm: 'objective-c',
  scala: 'scala',
  dart: 'dart',
  lua: 'lua',
  pl: 'perl',
  pm: 'perl',
  r: 'r',
  jl: 'julia',
  ex: 'elixir',
  exs: 'elixir',
  clj: 'clojure',
  cljs: 'clojure',
  fs: 'fsharp',
  fsx: 'fsharp',
  vb: 'vb',
  pas: 'pascal',
  sol: 'solidity',
  proto: 'protobuf',
  graphql: 'graphql',
  gql: 'graphql',
  sql: 'sql',
  pgsql: 'pgsql',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  fish: 'shell',
  ps1: 'powershell',
  psm1: 'powershell',
  bat: 'bat',
  cmd: 'bat',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'ini',
  ini: 'ini',
  cfg: 'ini',
  conf: 'ini',
  properties: 'ini',
  env: 'ini',
  xml: 'xml',
  svg: 'xml',
  plist: 'xml',
  xsd: 'xml',
  tf: 'hcl',
  tfvars: 'hcl',
  hcl: 'hcl',
  dockerfile: 'dockerfile',
  rst: 'restructuredtext',
  tcl: 'tcl',
  st: 'st',
  abap: 'abap',
  apex: 'apex',
  cls: 'apex',
  coffee: 'coffee',
  pug: 'pug',
  jade: 'pug',
  twig: 'twig',
  liquid: 'liquid',
  wgsl: 'wgsl',
  sv: 'systemverilog',
  svh: 'systemverilog',
  txt: 'plaintext',
  log: 'plaintext'
}

/** Files whose LANGUAGE is decided by the whole filename, not an extension. */
const LANGUAGE_BY_FILENAME: Record<string, string> = {
  dockerfile: 'dockerfile',
  containerfile: 'dockerfile',
  makefile: 'plaintext',
  gemfile: 'ruby',
  rakefile: 'ruby',
  '.gitignore': 'plaintext',
  '.dockerignore': 'plaintext',
  '.npmrc': 'ini',
  '.editorconfig': 'ini',
  '.env': 'ini'
}

/**
 * Monaco language id for a workspace path. Falls back to `plaintext` so an
 * unknown file still opens in the editor (highlighting off, editing intact).
 */
export function languageFor(path: string): string {
  const name = (path.split('/').pop() ?? path).toLowerCase()
  const byName = LANGUAGE_BY_FILENAME[name]
  if (byName) return byName
  // Suffixed variants of a well-known NAME: `Dockerfile.dev`, `.env.local`.
  // Dotfiles keep their leading dot so `.env.local` still resolves via `.env`.
  const token = name.split('.').filter(Boolean)[0] ?? ''
  const lead = name.startsWith('.') ? `.${token}` : token
  if (LANGUAGE_BY_FILENAME[lead]) return LANGUAGE_BY_FILENAME[lead]
  const ext = name.includes('.') ? (name.split('.').pop() ?? '') : ''
  return LANGUAGE_BY_EXT[ext] ?? 'plaintext'
}
