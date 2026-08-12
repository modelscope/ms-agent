/** Parsed web_search result item (exa/unified `{results:[...]}` shape). */
export interface WebSearchResult {
  url: string
  title: string
  summary: string
}

/** Parse a web_search tool result into displayable items. Returns [] when the
 * payload isn't the unified `{results:[...]}` JSON (e.g. still streaming, or
 * a grep/glob text blob). Shared by the chat step card (result count +
 * favicons) and the right-rail detail (result cards). */
export function parseWebSearchResults(result: unknown): WebSearchResult[] {
  if (typeof result !== 'string' || !result) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(result)
  } catch {
    return []
  }
  const results = (parsed as { results?: unknown })?.results
  if (!Array.isArray(results)) return []
  return results.map((item) => {
    const r =
      item && typeof item === 'object' && !Array.isArray(item)
        ? (item as Record<string, unknown>)
        : {}
    const s = (v: unknown) => (typeof v === 'string' ? v : '')
    return {
      url: s(r.url),
      title: s(r.title),
      summary: s(r.summary) || s(r.content)
    }
  })
}

/** Site hostname for display (strips `www.`), '' when the url is invalid. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** Public favicon for a result url (Google's s2 service; consumers hide the
 * <img> on error so offline/blocked environments degrade gracefully). */
export function faviconOf(url: string): string {
  const host = hostOf(url)
  return host
    ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`
    : ''
}
