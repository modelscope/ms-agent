/**
 * Rewriting the relative references inside a previewed document.
 *
 * A markdown file is rendered by us, so its `![](./img/a.png)` would resolve
 * against the SPA route the user happens to be on and 404. Each reference is
 * resolved against the document's OWN path instead, then handed to a URL
 * builder for the raw-bytes route it really lives at.
 *
 * HTML previews need none of this: they run inside an iframe pointed at that
 * same raw route, so the browser resolves their references itself.
 */

/** References that must be left exactly as written: absolute URLs, protocol
 * relative URLs, data/blob payloads, in-page anchors and empty values. */
function isExternal(ref: string): boolean {
  return (
    ref === '' ||
    ref.startsWith('#') ||
    ref.startsWith('//') ||
    /^[a-z][a-z0-9+.-]*:/i.test(ref)
  )
}

/**
 * Resolve `ref` as written inside the file at `base` into a path relative to
 * the file tree's root. Returns null when the reference is not ours to rewrite
 * (external, or climbing out of the root).
 *
 * A leading `/` counts as root-relative: inside a previewed document the site
 * root means nothing, so it is the file tree the author meant.
 */
export function resolveRef(base: string, ref: string): string | null {
  if (isExternal(ref)) return null
  // `?query` / `#hash` are not part of the path but have to survive it.
  const cut = ref.search(/[?#]/)
  const suffix = cut === -1 ? '' : ref.slice(cut)
  const rawPath = cut === -1 ? ref : ref.slice(0, cut)
  if (!rawPath) return null

  const fromRoot = rawPath.startsWith('/')
  const dir = fromRoot ? [] : base.split('/').slice(0, -1)
  const out: string[] = [...dir]
  for (const seg of rawPath.split('/')) {
    if (seg === '' || seg === '.') continue
    if (seg === '..') {
      if (!out.length) return null // climbs past the root
      out.pop()
      continue
    }
    out.push(seg)
  }
  return out.length ? out.join('/') + suffix : null
}

/**
 * `(ref) => url` for the document at `base`, mapping every in-tree reference
 * through `rawUrl`. Undefined for references to leave untouched.
 */
export function makeRefResolver(
  base: string,
  rawUrl: (path: string) => string
): (ref: string) => string | undefined {
  return (ref) => {
    const path = resolveRef(base, ref)
    return path == null ? undefined : rawUrl(path)
  }
}
