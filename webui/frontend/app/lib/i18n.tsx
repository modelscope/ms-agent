import xEnUS from '@ant-design/x/locale/en_US'
import xZhCN from '@ant-design/x/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from 'react'
import en from './locales/en.json'
import zh from './locales/zh.json'

export type Lang = 'en' | 'zh'

export const LANG_COOKIE = 'ms-agent-webui:lang'
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365 // 1 year

function writeCookie(lang: Lang) {
  if (typeof document === 'undefined') return
  document.cookie = `${LANG_COOKIE}=${lang}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`
}

/**
 * The dictionary shape is derived from the English locale file — en.json is
 * the single source of truth for the key structure. zh.json must mirror it
 * (structurally typechecked by `Record<Lang, Dict>` below), so adding a new
 * string means editing BOTH app/lib/locales/en.json and zh.json.
 */
export type Dict = typeof en

const dict: Record<Lang, Dict> = { en, zh }

/** The dictionary for a language, outside React (route `meta` functions run
 * before/without the provider). Unknown values fall back to English. */
export function dictFor(lang: string | undefined): Dict {
  return lang === 'zh' ? dict.zh : dict.en
}

/**
 * XProvider's `locale` prop is typed `xLocale & antdLocale` and is forwarded to
 * BOTH antd's ConfigProvider and x's own LocaleContext, so it has to carry both
 * vocabularies. Passing antd's locale alone left every @ant-design/x component
 * on its built-in English defaults — visible as "Image / Code / Reset" in the
 * Mermaid diagram toolbar while the rest of the UI was Chinese.
 *
 * The two objects are disjoint apart from `locale` itself (same value in both),
 * so a plain merge is safe; antd's spread goes last so its `locale` string stays
 * authoritative for the date/number formatting that reads it.
 */
type AntdLocale = typeof enUS & typeof xEnUS

interface LangContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  t: Dict
  antdLocale: AntdLocale
}

const LangContext = createContext<LangContextValue | null>(null)

const antdLocales: Record<Lang, AntdLocale> = {
  en: { ...xEnUS, ...enUS },
  zh: { ...xZhCN, ...zhCN }
}

export function LangProvider({
  initialLang = 'en',
  children
}: {
  initialLang?: Lang
  children: React.ReactNode
}) {
  const [lang, setLangState] = useState<Lang>(initialLang)

  // Keep <html lang> in sync with the active language. The server-rendered
  // attribute is set in root.tsx Layout; this owns it on the client so it
  // survives a route change re-render (the root loader no longer revalidates on
  // navigation, but this makes the attribute correct regardless of loaderData).
  useEffect(() => {
    if (typeof document === 'undefined') return
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    writeCookie(next)
  }, [])

  const value = useMemo<LangContextValue>(
    () => ({ lang, setLang, t: dict[lang], antdLocale: antdLocales[lang] }),
    [lang, setLang]
  )

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

export function useT(): LangContextValue {
  const ctx = useContext(LangContext)
  if (!ctx) throw new Error('useT must be used inside <LangProvider>')
  return ctx
}
