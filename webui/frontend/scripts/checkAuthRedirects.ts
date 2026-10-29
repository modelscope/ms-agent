import assert from 'node:assert/strict'
import { RouterContextProvider } from 'react-router'
import { api } from '../app/lib/api'
import { loginDestination, redirectIfSignedOut } from '../app/lib/auth'

// `next` is attacker-controlled. URL normalization must not turn it into an
// external destination, nor send a signed-in visitor back into the login page.
for (const next of [
  null, '', 'https://evil.example', '//evil.example', '/\\evil.example',
  '/\t/evil.example', '/\n/evil.example', '/\r/evil.example',
  '/login', '/login/', '/login.data', '/a/../login'
]) assert.equal(loginDestination(next), '/', String(next))
assert.equal(loginDestination('/projects/123?tab=files#preview'), '/projects/123?tab=files#preview')

const redirects: string[] = []
Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: { location: {
    pathname: '/settings/models', search: '',
    replace: (url: string) => redirects.push(url)
  } }
})
try {
  // A platform gateway's 401 must retain the platform's authentication flow.
  redirectIfSignedOut(new Response(null, { status: 401 }))
  assert.deepEqual(redirects, [])
  redirectIfSignedOut(new Response(null, {
    status: 401, headers: { 'X-MS-Agent-Auth-Required': '1' }
  }))
  assert.deepEqual(redirects, ['/login?next=%2Fsettings%2Fmodels'])
} finally {
  Reflect.deleteProperty(globalThis, 'window')
}

const originalFetch = globalThis.fetch
const calls: { path: string; cookie: string | null; contentType: string | null; body: BodyInit | null | undefined }[] = []
let releaseAuth!: () => void
const authGate = new Promise<void>((resolve) => { releaseAuth = resolve })
let authCalls = 0

globalThis.fetch = async (input, init) => {
  const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).pathname
  const headers = new Headers(init?.headers)
  const cookie = headers.get('Cookie')
  calls.push({ path, cookie, contentType: headers.get('Content-Type'), body: init?.body })
  if (path === '/api/auth/status') {
    if (++authCalls === 2) releaseAuth()
    await authGate
  }
  return Response.json({
    code: 0,
    message: 'success',
    data: path === '/api/auth/status'
      ? { enabled: true, authenticated: true, username: cookie }
      : null
  })
}

try {
  await api.getRecoveryStatus()
  assert.equal(calls.at(-1)?.cookie, null)
  const { authMiddleware, requestAuth, requestCookie } = await import('../app/lib/auth.server')
  const runRequest = (cookie: string, next: () => Promise<Response>) => authMiddleware({
    request: new Request('http://localhost/', { headers: { Cookie: cookie } }),
    url: new URL('http://localhost/'),
    pattern: '/',
    params: {},
    context: new RouterContextProvider()
  }, next)

  const responses = await Promise.all(['visitor=A', 'visitor=B'].map(cookie => runRequest(cookie, async () => {
    assert.equal(requestCookie(), cookie)
    assert.equal(requestAuth().username, cookie)
    await api.getProject(cookie)
    await Promise.resolve()
    assert.equal(requestCookie(), cookie)
    await api.uploadWorkspaceFile(cookie, new File(['test'], 'test.txt'))
    return new Response('ok')
  })))
  assert.equal(authCalls, 2)
  for (const response of responses) assert.equal(response?.headers.get('Cache-Control'), 'no-store')
  for (const cookie of ['visitor=A', 'visitor=B']) {
    const projectCalls = calls.filter(call => call.path.startsWith(`/api/projects/${encodeURIComponent(cookie)}`))
    assert.equal(projectCalls.length, 2)
    assert.ok(projectCalls.every(call => call.cookie === cookie))
    assert.equal(projectCalls[0].contentType, 'application/json')
    assert.equal(projectCalls[1].contentType, null)
    assert.ok(projectCalls[1].body instanceof FormData)
    assert.equal((projectCalls[1].body.get('file') as File).name, 'test.txt')
  }

  assert.equal(requestCookie(), '')
  await api.getRecoveryStatus()
  assert.equal(calls.at(-1)?.cookie, null)

  await runRequest('visitor=server-only', async () => {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: {} })
    try {
      assert.equal(requestCookie(), 'visitor=server-only')
      await api.getRecoveryStatus()
      assert.equal(calls.at(-1)?.cookie, null)
    } finally {
      Reflect.deleteProperty(globalThis, 'window')
    }
    return new Response('ok')
  })
} finally {
  globalThis.fetch = originalFetch
}
console.log('[webui] Auth redirects, request-cookie isolation, browser headers and FormData passed')
