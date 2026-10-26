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

/** Only return to a path within this app, never a user-supplied external URL. */
export function loginDestination(value: string | null): string {
  if (!value?.startsWith('/') || value.startsWith('//') || /[\\\r\n\t]/.test(value))
    return '/'
  const path = new URL(value, 'http://localhost').pathname
  return /^\/login(?:\.data)?\/?$/.test(path) ? '/' : value
}

export function signInUrl() {
  return '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search)
}

export function redirectIfSignedOut(response: Response) {
  if (typeof window !== 'undefined' && response.headers.get('X-MS-Agent-Auth-Required') === '1') {
    window.location.replace(signInUrl())
  }
}
