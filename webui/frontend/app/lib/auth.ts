import { useRouteLoaderData } from 'react-router'

export interface AuthStatus {
  enabled: boolean
  authenticated: boolean
  username: string | null
}

export const AUTH_DISABLED: AuthStatus = {
  enabled: false,
  authenticated: true,
  username: null
}

export function useAuth() {
  const root = useRouteLoaderData('root') as { auth?: AuthStatus } | undefined
  return root?.auth ?? AUTH_DISABLED
}

/** `/login`, including its `.data` single-fetch request and a trailing slash. */
const LOGIN_PATH = /^\/login(?:\.data)?\/?$/

export function isLoginPath(pathname: string): boolean {
  return LOGIN_PATH.test(pathname)
}

/** The login page with the in-app path to return to after signing in. */
export function loginUrl(next: string): string {
  return '/login?next=' + encodeURIComponent(next)
}

/** Only return to a path within this app, never a user-supplied external URL. */
export function loginDestination(value: string | null): string {
  if (!value?.startsWith('/') || value.startsWith('//') || /[\\\r\n\t]/.test(value))
    return '/'
  const path = new URL(value, 'http://localhost').pathname
  return isLoginPath(path) ? '/' : value
}

export function signInUrl() {
  return loginUrl(window.location.pathname + window.location.search)
}

export function redirectIfSignedOut(response: Response) {
  if (typeof window !== 'undefined' && response.headers.get('X-MS-Agent-Auth-Required') === '1') {
    window.location.replace(signInUrl())
  }
}
