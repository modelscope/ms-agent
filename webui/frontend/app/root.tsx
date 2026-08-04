import { StyleProvider } from '@ant-design/cssinjs'
import { XProvider } from '@ant-design/x'
import { App as AntdApp } from 'antd'
import { useEffect } from 'react'
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
  useRouteError,
  useRouteLoaderData
} from 'react-router'

import './app.css'
import { NProgressHandler } from '~/components/common/NProgressHandler'
import { type ApiError, registerApiErrorReporter } from '~/lib/api'
import { getDesignTokenStyleContent } from '~/lib/designTokens'
import { LANG_COOKIE, dictFor, type Lang, LangProvider, useT } from '~/lib/i18n'
import { getMsaAntdTheme, msaModalProps } from '~/lib/msaTheme'
import { THEME_COOKIE, type Theme, ThemeProvider, useTheme } from '~/lib/theme'

interface RootData {
  initialTheme: Theme
  initialLang: Lang
}

function readCookie(cookie: string, name: string) {
  const re = new RegExp(`(?:^|; )${name.replace(/[-:]/g, '\\$&')}=([^;]+)`)
  return cookie.match(re)?.[1]
}

/** First supported language from the browser's Accept-Language preference
 * list (quality-ordered by the browser itself), for first visits with no
 * language cookie yet. Resolved on the server so SSR and hydration agree. */
function langFromAcceptLanguage(header: string): Lang | null {
  for (const part of header.split(',')) {
    const tag = part.split(';')[0].trim().toLowerCase()
    if (!tag) continue
    if (tag.startsWith('zh')) return 'zh'
    if (tag.startsWith('en')) return 'en'
  }
  return null
}

export async function loader({ request }: { request: Request }) {
  const cookie = request.headers.get('Cookie') || ''
  const themeRaw = readCookie(cookie, THEME_COOKIE)
  const langRaw = readCookie(cookie, LANG_COOKIE)
  const initialTheme: Theme = themeRaw === 'dark' ? 'dark' : 'light'
  // Explicit choice (cookie) wins; a first visit falls back to the browser's
  // preferred language, then to English.
  const initialLang: Lang =
    langRaw === 'zh' || langRaw === 'en'
      ? langRaw
      : (langFromAcceptLanguage(request.headers.get('Accept-Language') || '') ??
        'en')
  return { initialTheme, initialLang } satisfies RootData
}

/** Universal title fallback: any route without its own `meta` (e.g. a
 * redirect-only index route) still gets a proper document title instead of the
 * browser showing the bare URL. Leaf routes override this entirely. */
export function meta({ loaderData }: { loaderData?: RootData }) {
  return [{ title: dictFor(loaderData?.initialLang).brand }]
}

export function Layout({ children }: { children: React.ReactNode }) {
  const data = useRouteLoaderData('root') as RootData | undefined
  const initialTheme: Theme = data?.initialTheme ?? 'light'
  const initialLang: Lang = data?.initialLang ?? 'en'

  return (
    <html
      lang={initialLang === 'zh' ? 'zh-CN' : 'en'}
      className={initialTheme === 'dark' ? 'dark' : undefined}
      suppressHydrationWarning
    >
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        {/* No hardcoded <title> here: it would win over the per-route titles
            rendered by <Meta /> (the browser keeps the FIRST one). */}
        <link rel="icon" type="image/x-icon" href="/favicon.ico" />
        <style
          dangerouslySetInnerHTML={{ __html: getDesignTokenStyleContent() }}
        />
        <Meta />
        <Links />
      </head>
      <body className="h-full overflow-x-hidden">
        <LangProvider initialLang={initialLang}>
          <ThemeProvider initialTheme={initialTheme}>
            <ThemedRoot>{children}</ThemedRoot>
          </ThemeProvider>
        </LangProvider>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  )
}

function ThemedRoot({ children }: { children: React.ReactNode }) {
  const { antdLocale } = useT()
  const { theme } = useTheme()
  return (
    <StyleProvider layer>
      <XProvider
        locale={antdLocale}
        theme={getMsaAntdTheme(theme)}
        modal={msaModalProps}
      >
        <AntdApp>
          <NProgressHandler />
          <ApiErrorBridge />
          {children}
        </AntdApp>
      </XProvider>
    </StyleProvider>
  )
}

// Wires the REST client's global error reporter to antd's themed `message` so
// every failed request surfaces one consistent toast. Must live inside <App>
// to obtain the message instance via the hook (per project convention).
function ApiErrorBridge() {
  const { message } = AntdApp.useApp()
  const { t } = useT()
  useEffect(() => {
    registerApiErrorReporter((msg: string, err: ApiError) => {
      const text =
        msg || (err.status === 0 ? t.errors.network : t.errors.requestFailed)
      message.error(text)
    })
    return () => registerApiErrorReporter(null)
  }, [message, t])
  return null
}

export default function App() {
  return <Outlet />
}

export function ErrorBoundary() {
  const error = useRouteError()
  const title = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : 'Unexpected error'
  const detail =
    isRouteErrorResponse(error) && typeof error.data === 'string'
      ? error.data
      : error instanceof Error
        ? error.message
        : 'Something went wrong.'

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-lg space-y-3 rounded-lg border border-red-200 bg-red-50 p-6 dark:border-red-900 dark:bg-red-950">
        <h1 className="text-lg font-semibold text-red-700 dark:text-red-300">
          {title}
        </h1>
        <p className="text-sm text-red-600 dark:text-red-400">{detail}</p>
      </div>
    </div>
  )
}
