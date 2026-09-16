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
  redirect,
  useRouteError,
  useRouteLoaderData
} from 'react-router'

import './app.css'
import { NProgressHandler } from '~/components/common/NProgressHandler'
import { renderAntdEmpty } from '~/components/common/EmptyState'
import { ErrorState } from '~/components/common/ErrorState'
import { api, ApiError, orThrow, registerApiErrorReporter } from '~/lib/api'
import { getAntdCssHref } from '~/lib/antdStyle.server'
import { getDesignTokenStyleContent } from '~/lib/designTokens'
import { SERVER_HOSTED_MODE } from '~/lib/env'
import { LANG_COOKIE, dictFor, type Lang, LangProvider, useT } from '~/lib/i18n'
import { getMsaAntdTheme, msaModalProps } from '~/lib/msaTheme'
import {
  SCROLLBAR_WIDTH_SCRIPT,
  useScrollbarWidthVar
} from '~/lib/scrollbarWidth'
import {
  SCHEME_COOKIE,
  THEME_COOKIE,
  type Theme,
  type ThemePref,
  ThemeProvider,
  useTheme
} from '~/lib/theme'
import { MsaButton } from './components/common/MsaButton'

interface RootData {
  initialPref: ThemePref
  initialSystemTheme: Theme
  initialLang: Lang
  /** Hashed filename of the baked antd stylesheet, `null` when it is missing. */
  antdCssHref: string | null
  /** `MS_AGENT_FRONTEND_HOSTED_MODE=1`: this instance runs on a machine the user
   * has no view of, so controls that ask them to name a path on it are hidden.
   * Lives on ROOT because the controls sit under different layouts — see
   * `useHosted`. */
  hosted: boolean
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
  const recovery = await orThrow(api.getRecoveryStatus().catch((error) => {
    // Preserve pages that can render without an API, including the SSR package check.
    if (error instanceof ApiError && error.status === 0) return null
    throw error
  }))
  if (recovery?.required && new URL(request.url).pathname !== '/recovery') {
    throw redirect('/recovery')
  }
  const cookie = request.headers.get('Cookie') || ''
  const themeRaw = readCookie(cookie, THEME_COOKIE)
  const schemeRaw = readCookie(cookie, SCHEME_COOKIE)
  const langRaw = readCookie(cookie, LANG_COOKIE)
  // Default to following the OS. The server can't read `prefers-color-scheme`,
  // so the browser mirrors it into SCHEME_COOKIE and we resolve from that;
  // absent (first ever visit) it falls back to light.
  const initialPref: ThemePref =
    themeRaw === 'dark' || themeRaw === 'light' || themeRaw === 'system'
      ? themeRaw
      : 'system'
  const initialSystemTheme: Theme = schemeRaw === 'dark' ? 'dark' : 'light'
  // Explicit choice (cookie) wins; a first visit falls back to the browser's
  // preferred language, then to English.
  const initialLang: Lang =
    langRaw === 'zh' || langRaw === 'en'
      ? langRaw
      : (langFromAcceptLanguage(request.headers.get('Accept-Language') || '') ??
        'en')
  return {
    initialPref,
    initialSystemTheme,
    initialLang,
    // Sent through the loader because the constant is `false` in the browser (the
    // client build has no `process.env`); this is what makes the value available
    // to components, via `useHosted()`. Declared in `lib/env.ts`.
    hosted: SERVER_HOSTED_MODE,
    // antd runs with `zeroRuntime` (see msaTheme.ts), so no component CSS is
    // ever emitted at render time — the pre-baked file is it.
    antdCssHref: getAntdCssHref()
  } satisfies RootData
}

/** Universal title fallback: any route without its own `meta` (e.g. a
 * redirect-only index route) still gets a proper document title instead of the
 * browser showing the bare URL. Leaf routes override this entirely. */
export function meta({ loaderData }: { loaderData?: RootData }) {
  return [{ title: dictFor(loaderData?.initialLang).brand }]
}

export function Layout({ children }: { children: React.ReactNode }) {
  const data = useRouteLoaderData('root') as RootData | undefined
  const initialPref: ThemePref = data?.initialPref ?? 'system'
  const initialSystemTheme: Theme = data?.initialSystemTheme ?? 'light'
  const initialLang: Lang = data?.initialLang ?? 'en'
  const initialTheme: Theme =
    initialPref === 'system' ? initialSystemTheme : initialPref

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

        {/* THE cascade layer order for the whole app. Declared BOTH here and at
            the top of app.css, character for character — keep the two in sync.

            A layer ranks where its name is first seen, so the copy the browser
            parses first fixes the order and the other is a harmless repeat.
            Two copies because neither position is dependable alone: app.css
            cannot be the only one (Vite/React Router decide where its
            <link>/<style> lands and move it on hydration — critical.css is
            dropped and app.css is re-injected at the *end* of <head>, i.e.
            possibly after the baked antd sheet), and this one cannot either — it
            is React-owned, and when React re-mounts this Layout (the error
            boundary taking over after a client-side render error) it removes and
            re-appends these nodes, landing them AFTER app.css. That inversion
            let `antd` out-rank `utilities` and stripped every antd component on
            the error page back to its default chrome.

            Any layer name missing from this list gets appended *after*
            `utilities` the first time it is seen, i.e. it silently wins over
            Tailwind. `properties` is Tailwind's own `--tw-*` fallback shim and
            must stay first (lowest); `antd`/`antdx` come from the baked sheet
            below and must sit under `utilities` so utilities keep overriding
            antd without `!important`. */}
        <style
          dangerouslySetInnerHTML={{
            __html:
              '@layer properties, theme, base, antd, antdx, components, utilities;'
          }}
        />

        <style
          dangerouslySetInnerHTML={{ __html: getDesignTokenStyleContent() }}
        />
        <Meta />
        <Links />
        {/* Baked antd/x stylesheet (zeroRuntime — see scripts/genAntdCss.tsx).
            It carries no order statement of its own, only `@layer antd{…}` /
            `@layer antdx{…}` blocks, so it is position-independent: the statement
            above has already fixed where those two layers rank. Which is what
            makes sitting last here fine — and it matches the shape antd documents
            for SSR (the order statement loads before the layers are used), at no
            download cost, since the preload scanner finds every <head> link in
            one pass.
            Absent only when the bake is missing — the loader logs that loudly. */}
        {data?.antdCssHref ? (
          <link rel="stylesheet" href={data.antdCssHref} />
        ) : null}
      </head>
      <body className="h-full overflow-x-hidden">
        {/* Before anything below it lays out — see the script's own comment. */}
        <script dangerouslySetInnerHTML={{ __html: SCROLLBAR_WIDTH_SCRIPT }} />
        <LangProvider initialLang={initialLang}>
          <ThemeProvider
            initialPref={initialPref}
            initialSystemTheme={initialSystemTheme}
          >
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
  useScrollbarWidthVar()
  return (
    <StyleProvider layer>
      <XProvider
        locale={antdLocale}
        theme={getMsaAntdTheme(theme)}
        modal={msaModalProps}
        // Every antd data component falls back to its own "No data" illustration
        // when the call site names no empty content; this replaces all of them
        // with the project's, so a new Select or Table is themed by default
        // instead of by whoever remembers to pass `notFoundContent`.
        renderEmpty={renderAntdEmpty}
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
      // No message means the failure was not reported by our backend at all —
      // something in FRONT of it answered (a proxy/gateway 502, an upstream
      // 504) with a body carrying no envelope. Naming the number keeps a burst
      // of such toasts distinguishable and reportable instead of an
      // indistinguishable wall of "Request failed".
      // `code`, not `status`: the two are equal for a transport failure, but a
      // rejection the body declares itself (readFailure) can arrive with a 2xx
      // status, and only `code` then holds the real one.
      // The reason phrase is appended when there is one, since it is the only
      // words such a failure carries — absent over HTTP/2, hence the bare-code
      // fallback. It pairs with `status` ONLY: for the 200-OK-with-code-400 case
      // above, "400 OK" would describe neither half truthfully.
      const detail =
        err.code === err.status && err.statusText
          ? `${err.status} ${err.statusText}`
          : String(err.code)
      const text = msg
        ? msg
        : err.status === 0
          ? t.errors.network
          : `${t.errors.requestFailed}: ${detail}`
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
  // Read nothing off the error object but its message: a server-rendered error
  // arrives here as a plain `Error`, so `status` and the class are gone and
  // reading them broke hydration. Loaders carry status via `orThrow` instead.
  const status = routeError ? error.status : undefined
  // No status means a client-side exception; its own name is unavailable (see
  // above), so use a fixed phrase and let the message explain.
  const code = status ? String(status) : t.errors.unexpected
  // The server's own message is the explanation — it is the only text that knows
  // what actually failed. Inventing a per-status sentence here would replace
  // "project not found" with something vaguer.
  const reported = routeError
    ? typeof error.data === 'string' && error.data
      ? error.data
      : error.statusText
    : error instanceof Error
      ? error.message
      : String(error ?? '')
  // Some failures carry no words at all (backend never answered, or an empty
  // gateway body), which left the headline over an empty paragraph.
  const description =
    reported || (status === 502 ? t.errors.network : t.errors.requestFailed)

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
