import { Input } from 'antd'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { MsaButton } from '~/components/common/MsaButton'
import { api, ApiError } from '~/lib/api'
import { loginDestination } from '~/lib/auth'
import { useT } from '~/lib/i18n'

export default function LoginPage() {
  const { t } = useT()
  const [params] = useSearchParams()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<'invalid' | 'limited' | 'unavailable' | null>(null)

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await api.login(username, password)
      window.location.replace(loginDestination(params.get('next')))
    } catch (error) {
      setError(error instanceof ApiError && error.status === 401 ? 'invalid'
        : error instanceof ApiError && error.status === 429 ? 'limited' : 'unavailable')
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-msa-bg-1 p-6">
      <div className="w-full max-w-sm rounded-2xl border border-msa-line-1 bg-msa-bg-2 p-8">
        <h1 className="m-0 text-2xl font-semibold text-msa-text-1">{t.auth.title}</h1>
        <p className="mb-7 mt-2 text-sm text-msa-text-3">{t.auth.description}</p>
        <form onSubmit={signIn} className="flex flex-col gap-5">
          <div>
            <label htmlFor="username" className="mb-2 block text-sm text-msa-text-2">{t.auth.username}</label>
            <Input id="username" name="username" autoComplete="username" required maxLength={256}
              value={username} onChange={(event) => setUsername(event.target.value)} size="large" />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-sm text-msa-text-2">{t.auth.password}</label>
            <Input.Password id="password" name="password" autoComplete="current-password" required maxLength={4096}
              value={password} onChange={(event) => setPassword(event.target.value)} size="large" />
          </div>
          {error ? <p role="alert" className="m-0 text-sm text-msa-text-1">{t.auth[error]}</p> : null}
          <MsaButton htmlType="submit" variant="primary" size="large" loading={busy}>{t.auth.signIn}</MsaButton>
          <p className="m-0 text-center text-xs text-msa-text-3">{t.auth.remember}</p>
        </form>
      </div>
    </main>
  )
}
