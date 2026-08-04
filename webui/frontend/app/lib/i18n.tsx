import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import {
  createContext,
  useCallback,
  useContext,
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

type AntdLocale = typeof enUS

interface LangContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  t: Dict
  antdLocale: AntdLocale
}

const LangContext = createContext<LangContextValue | null>(null)

const antdLocales: Record<Lang, AntdLocale> = { en: enUS, zh: zhCN }

export function LangProvider({
  initialLang = 'en',
  children
}: {
  initialLang?: Lang
  children: React.ReactNode
}) {
  const [lang, setLangState] = useState<Lang>(initialLang)

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
