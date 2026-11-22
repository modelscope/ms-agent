import { AsyncLocalStorage } from 'node:async_hooks'
import { redirect, redirectDocument, type MiddlewareFunction } from 'react-router'
import { api, ApiError, registerRequestCookieReader } from './api'
import { AUTH_DISABLED, isLoginPath, loginDestination, loginUrl, type AuthStatus } from './auth'

interface RequestAuth {
  cookie: string
  status: AuthStatus
}

// Loaders run concurrently. Never put a visitor's cookie in a module-global
// fetch default: another request could then inherit that visitor's access.
const requests = new AsyncLocalStorage<RequestAuth>()

export function requestCookie() {
  return requests.getStore()?.cookie ?? ''
}

registerRequestCookieReader(requestCookie)

export function requestAuth() {
  return requests.getStore()?.status ?? AUTH_DISABLED
}

export const authMiddleware: MiddlewareFunction<Response> = async ({ request }, next) => {
  return requests.run({ cookie: request.headers.get('Cookie') ?? '', status: AUTH_DISABLED }, async () => {
    let status: AuthStatus
    try {
      status = await api.getAuthStatus()
    } catch (error) {
      // The build's standalone SSR check has no API. Business loaders still
      // fail normally; this fallback never supplies credentials to the backend.
      if (!(error instanceof ApiError) || error.status !== 0) throw error
      return next()
    }
    requests.getStore()!.status = status
    const url = new URL(request.url)
    const isLogin = isLoginPath(url.pathname)
    if (status.enabled && !status.authenticated && !isLogin) {
      throw redirectDocument(loginUrl(url.pathname.replace(/\.data$/, '') + url.search))
    }
    if (isLogin && (!status.enabled || status.authenticated)) {
      throw redirect(loginDestination(url.searchParams.get('next')))
    }
    const response = await next()
    if (status.enabled) response.headers.set('Cache-Control', 'no-store')
    return response
  })
}
