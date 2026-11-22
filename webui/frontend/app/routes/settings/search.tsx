import { Input, Select } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { MsaSwitch } from '~/components/common/MsaSwitch'
import { api } from '~/lib/api'
import { useOnProjectSettingsChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { SearchProvider, SearchSettings } from '~/lib/types'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/search'
import { KeyResetButton, KeyStatusTag } from '~/components/common/KeyStatus'

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.navSearch, t.settings.title) }]
}

export default function SearchSettingsPage() {
  const { t } = useT()
  const [providers, setProviders] = useState<SearchProvider[]>([])
  const [settings, setSettings] = useState<SearchSettings | null>(null)
  // What the user typed, kept PER PROVIDER and only for this page visit. The
  // stored key is never sent to the client, so without this the field blanked
  // itself the moment a save landed and there was no way to re-read what you had
  // just entered. Keyed by provider so a key typed for one engine can't be
  // submitted as another's after switching the dropdown.
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({})
  // Last value successfully saved per provider, so repeated blurs don't re-PUT
  // the same secret.
  const savedDrafts = useRef<Record<string, string>>({})

  useEffect(() => {
    api.listSearchProviders().then(setProviders)
  }, [])

  const loadSettings = useCallback(() => {
    api.getSearchSettings().then(setSettings)
  }, [])
  useEffect(loadSettings, [loadSettings])
  // Web-search config is a global singleton edited from the composer pill and by
  // external API calls (relayed as a project-settings change) — re-read so this
  // page stays in sync. Typed key drafts live in separate state, so a refresh
  // here never discards what the user is entering.
  useOnProjectSettingsChanged(loadSettings)

  const provider = providers.find((p) => p.id === settings?.provider) ?? null
  const needsKey = provider?.requires_key ?? true
  const hasKey = !!settings?.has_key
  const providerId = settings?.provider ?? ''
  const keyDraft = keyDrafts[providerId] ?? ''
  // `has_key` now means "this page has one on file", so it is exactly the
  // condition under which a reset has something to remove.
  const canReset = hasKey

  const save = async (patch: {
    enabled?: boolean
    provider?: string
    api_key?: string
  }) => {
    if (!settings) return
    const target = patch.provider ?? settings.provider
    try {
      const next = await api.putSearchSettings({
        enabled: patch.enabled ?? settings.enabled,
        provider: target,
        // Omitted entirely unless a replacement was typed — sending '' would
        // clear the stored key on every incidental save.
        ...(patch.api_key !== undefined ? { api_key: patch.api_key } : {})
      })
      setSettings(next)
      if (patch.api_key !== undefined) {
        savedDrafts.current[target] = patch.api_key
      }
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    }
  }

  // '' is the update schema's "clear it" signal. The local draft has to go too,
  // or a stale typed value would sit in a field the server now considers empty
  // and get re-submitted on the next blur, undoing the reset.
  const resetKey = async () => {
    delete savedDrafts.current[providerId]
    setKeyDrafts((prev) => ({ ...prev, [providerId]: '' }))
    await save({ api_key: '' })
  }

  // The toggle carries no policy restriction: enabling web search without a key
  // is a state the user is allowed to be in (a key may also arrive from the
  // environment later). The only thing shown is a factual warning that calls
  // will fail meanwhile — never a disabled control.
  //
  // A provider with a keyless tier is excluded: for it, no key means "reduced
  // free quota", not "calls will fail", so the red warning would be simply
  // untrue. Those get the neutral keyless note instead.
  const keyless = !!provider?.supports_keyless
  const enabledWithoutKey =
    needsKey && !hasKey && !keyless && !!settings?.enabled
  const keylessActive = keyless && !hasKey && !!settings?.enabled

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4 text-base font-semibold text-msa-text-1">
          {t.settings.searchTitle}
        </div>

        <div className="space-y-5">
          <div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-msa-text-2">
                {t.settings.searchEnableLabel}
              </span>
              <MsaSwitch
                checked={!!settings?.enabled}
                disabled={!settings}
                onChange={(v) => save({ enabled: v })}
              />
            </div>
            <div
              className={`mt-1.5 text-xs ${
                enabledWithoutKey ? 'text-msa-text-danger' : 'text-msa-text-3'
              }`}
            >
              {enabledWithoutKey
                ? t.settings.searchEnabledNoKey
                : keylessActive
                  ? t.settings.searchKeylessActive
                  : t.settings.searchEnableDesc}
            </div>
          </div>

          <div>
            <div className="mb-1.5 text-sm text-msa-text-1">
              {t.settings.searchProviderLabel}
            </div>
            <Select
              className="w-full max-w-[360px]"
              value={settings?.provider}
              loading={!settings}
              options={providers.map((p) => ({
                value: p.id,
                label: p.label
              }))}
              onChange={(v) => save({ provider: v })}
            />
          </div>

          {needsKey ? (
            <div>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-sm text-msa-text-1">
                  {t.settings.searchKeyLabel}
                </span>
                {/* Since the key itself can't be shown, this tag is the only
                    signal that one is stored — see KeyStatusTag. */}
                <KeyStatusTag set={hasKey}>
                  {hasKey
                    ? t.settings.searchKeyConfigured
                    : keyless
                      ? t.settings.searchKeyOptional
                      : t.settings.searchKeyMissing}
                </KeyStatusTag>
              </div>
              {/* The reset lives in the field's suffix, next to the visibility
                  toggle: it acts on this one value, so it belongs to the input
                  rather than to the label row (which carries the read-only
                  status tag) or to a control floating beside the field. */}
              <Input.Password
                className="w-full max-w-[360px]"
                value={keyDraft}
                disabled={!settings}
                placeholder={
                  hasKey
                    ? t.settings.searchKeyPlaceholderSet
                    : t.settings.searchKeyPlaceholder
                }
                onChange={(e) =>
                  setKeyDrafts((prev) => ({
                    ...prev,
                    [providerId]: e.target.value
                  }))
                }
                onBlur={() => {
                  const next = keyDraft.trim()
                  if (next && next !== savedDrafts.current[providerId]) {
                    save({ api_key: next })
                  }
                }}
                suffix={
                  canReset ? (
                    <KeyResetButton
                      confirmTitle={t.settings.searchKeyResetConfirm.replace(
                        '{name}',
                        provider?.label ?? providerId
                      )}
                      confirmDesc={t.settings.searchKeyResetConfirmDesc}
                      okText={t.settings.searchKeyReset}
                      tooltip={t.settings.searchKeyResetTip}
                      onConfirm={resetKey}
                    />
                  ) : null
                }
              />
              <div className="mt-1.5 text-xs text-msa-text-3">
                {t.settings.searchKeyNote}
              </div>
            </div>
          ) : (
            <div className="text-xs text-msa-text-3">
              {t.settings.searchNoKeyNeeded}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
