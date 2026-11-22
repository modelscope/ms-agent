import { useState } from 'react'
import { api } from '~/lib/api'
import { useAuth } from '~/lib/auth'
import { useT } from '~/lib/i18n'
import { MsaButton } from './MsaButton'

export function SignOutButton() {
  const { enabled } = useAuth()
  const { t } = useT()
  const [busy, setBusy] = useState(false)
  if (!enabled) return null

  async function signOut() {
    setBusy(true)
    try {
      await api.logout()
      window.location.replace('/login')
    } catch {
      // The shared API client displays the error; keep the current session.
      setBusy(false)
    }
  }

  return (
    <div className="mb-4 flex justify-end">
      <MsaButton onClick={signOut} loading={busy}>{t.auth.signOut}</MsaButton>
    </div>
  )
}
