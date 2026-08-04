import { dictFor, type Dict } from '~/lib/i18n'

/**
 * Localized document titles, resolved inside route `meta` functions.
 *
 * `meta` runs outside React (no LangProvider), so the language comes from the
 * ROOT match's loader data (`initialLang` — the cookie, else the browser's
 * Accept-Language), the very same value the UI renders with, so the title and
 * the page never disagree.
 *
 * Typed loosely on purpose: every route's generated `Route.MetaArgs["matches"]`
 * is a different tuple, and all we need from it is the root match's
 * `initialLang`.
 */
export function metaDict(
  matches: readonly ({ id?: string; loaderData?: unknown } | undefined)[]
): Dict {
  const root = matches.find((m) => m?.id === 'root')
  const lang = (root?.loaderData as { initialLang?: string } | undefined)
    ?.initialLang
  return dictFor(lang)
}

/**
 * Build a document title: context-specific parts first (most specific →
 * least), always suffixed with the product name, e.g.
 * `修复登录 bug · 我的项目 · 魔搭 MS Agent`. Blank parts are dropped, so a
 * missing project/session name just shortens the title.
 */
export function pageTitle(dict: Dict, ...parts: (string | undefined)[]): string {
  return [...parts.map((p) => p?.trim()).filter(Boolean), dict.brand].join(' · ')
}
