import assert from 'node:assert/strict'
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
console.log('[webui] Auth redirects and platform 401 handling passed')
