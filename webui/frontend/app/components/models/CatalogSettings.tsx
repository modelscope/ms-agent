import { Button } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { CatalogStatus } from '~/lib/types'

export function CatalogSettings() {
  const { t } = useT()
  const [status, setStatus] = useState<CatalogStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  useEffect(() => {
    let current = true
    api.getCatalogStatus().then((value) => { if (current) setStatus(value) }).catch(() => {})
    return () => { current = false }
  }, [])

  const update = async () => {
    setBusy(true)
    setResult('')
    try {
      const value = await api.updateCatalog()
      setStatus(value)
      setResult(value.result ?? '')
    } catch {
      setResult('failed')
    } finally {
      setBusy(false)
    }
  }
  if (!status) return null
  const active = status.active
  const date = (value?: string | null) => value?.slice(0, 10) ?? '—'
  return (
    <section className="mb-5 shrink-0 rounded-lg border border-msa-line-1 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium text-msa-text-1">{t.settings.catalogTitle}</div>
          <div className="mt-1 text-xs text-msa-text-2" title={active.revision ?? undefined}>
            {active.available
              ? `${active.location === 'cache' ? t.settings.catalogCache : t.settings.catalogBundled} · ${date(active.fetched_at)} · ${active.revision?.slice(7, 19)}`
              : t.settings.catalogUnavailable}
          </div>
        </div>
        <Button size="small" onClick={update} loading={busy} disabled={status.policy === 'bundled'}>
          {t.settings.catalogUpdate}
        </Button>
      </div>
      <div className="mt-2 text-xs text-msa-text-2" role="status" aria-live="polite">
        {status.pending
          ? `${t.settings.catalogPending} · ${date(status.pending.fetched_at)} · ${status.pending.revision?.slice(7, 19)}`
          : result === 'failed' ? t.settings.catalogFailed
          : result === 'updated' ? t.settings.catalogCurrent
          : result === 'busy' ? t.settings.catalogBusy
          : status.policy === 'bundled' ? t.settings.catalogPinned
          : t.settings.catalogDescription}
      </div>
    </section>
  )
}
