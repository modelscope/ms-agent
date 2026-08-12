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
import { ErrorState } from '~/components/common/ErrorState'
import { ApiError, registerApiErrorReporter } from '~/lib/api'
import { getDesignTokenStyleContent } from '~/lib/designTokens'
import { LANG_COOKIE, dictFor, type Lang, LangProvider, useT } from '~/lib/i18n'
import { getMsaAntdTheme, msaModalProps } from '~/lib/msaTheme'
import { THEME_COOKIE, type Theme, ThemeProvider, useTheme } from '~/lib/theme'
import { MsaButton } from './components/common/MsaButton'

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
  const { t } = useT()
  const routeError = isRouteErrorResponse(error)
  // A loader that let an API failure propagate carries the real HTTP status on
  // the ApiError — without reading it, a missing project/session would show no
  // status at all when it is plainly a 404.
  const apiStatus = error instanceof ApiError ? error.status : undefined
  const status = routeError ? error.status : apiStatus
  // The status code IS the headline. A client-side exception carries no status,
  // so it falls back to the error's OWN name (`TypeError`) rather than a phrase
  // we made up — same principle as the description below.
  const code = status
    ? String(status)
    : error instanceof Error
      ? error.name
      : undefined
  // The server's own message is the explanation — it is the only text that knows
  // what actually failed. Inventing a per-status sentence here would replace
  // "project not found" with something vaguer.
  const description = routeError
    ? typeof error.data === 'string' && error.data
      ? error.data
      : error.statusText
    : error instanceof Error
      ? error.message
      : String(error ?? '')

  return (
    <ErrorState
      code={code}
      description={description}
      action={
        // Full page load, not a router navigation: whatever broke may have left
        // the client in a bad state, so going home should re-bootstrap the app.
        // Navigating via onClick keeps this a real <button> — with `href` antd
        // renders an <a>, whose own color rule beats the variant's `text-white`
        // and leaves dark text on the dark primary fill.
        <MsaButton
          variant="primary"
          onClick={() => {
            window.location.href = '/'
          }}
        >
          {t.errors.backHome}
        </MsaButton>
      }
    />
  )
}
