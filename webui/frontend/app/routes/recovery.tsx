import { useRef, useState } from 'react'
import { useLoaderData } from 'react-router'
import { ErrorState } from '~/components/common/ErrorState'
import { MsaButton } from '~/components/common/MsaButton'
import { api, orThrow } from '~/lib/api'
import { useT } from '~/lib/i18n'

export async function loader() {
  return orThrow(api.getRecoveryStatus())
}

export default function RecoveryPage() {
  const initial = useLoaderData<typeof loader>()
  const { t } = useT()
  const [status, setStatus] = useState(initial)
  const [deferred, setDeferred] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [networkError, setNetworkError] = useState(false)
  const pending = useRef(false)

  const recover = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setNetworkError(false)
    try {
      setStatus(await api.repairDefaultProject())
      setConfirming(false)
    } catch {
      setNetworkError(true)
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  const description = !status.required
    ? t.recovery.successDescription
    : deferred ? t.recovery.deferredDescription : t.recovery.description
  const failure = networkError ? t.recovery.networkError
    : status.error ? t.recovery[status.error] : null

  return (
    <ErrorState
      code={status.required ? t.recovery.title : t.recovery.successTitle}
      description={description}
      action={
        <div className="flex max-w-[420px] flex-col gap-4">
          {failure && <p role="alert" className="m-0 text-sm text-msa-text-1">{failure}</p>}
          {status.backup_path && <p className="m-0 break-all text-xs text-msa-text-3">{t.recovery.backup}: {status.backup_path}</p>}
          {!status.required ? (
            <MsaButton variant="primary" onClick={() => { window.location.href = '/' }}>
              {t.recovery.continue}
            </MsaButton>
          ) : confirming ? (
            <>
              <p className="m-0 text-sm text-msa-text-2">{t.recovery.confirmDescription}</p>
              <div className="flex flex-wrap justify-center gap-3 sm:justify-start">
                <MsaButton disabled={busy} onClick={() => setConfirming(false)}>{t.recovery.cancel}</MsaButton>
                <MsaButton variant="primary" loading={busy} onClick={recover}>{t.recovery.confirm}</MsaButton>
              </div>
            </>
          ) : (
            <div className="flex flex-wrap justify-center gap-3 sm:justify-start">
              <MsaButton onClick={() => { setDeferred(true); setConfirming(false) }}>{t.recovery.later}</MsaButton>
              <MsaButton variant="primary" onClick={() => { setDeferred(false); setConfirming(true) }}>
                {t.recovery.restore}
              </MsaButton>
            </div>
          )}
        </div>
      }
    />
  )
}
