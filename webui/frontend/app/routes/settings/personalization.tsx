import { Input, Radio } from 'antd'
import { useEffect, useState } from 'react'
import {
  MemoryModelConfig,
  type MemoryModelValue
} from '~/components/project/MemoryModelConfig'
import { MsaSwitch } from '~/components/common/MsaSwitch'
import { MsaTextArea } from '~/components/common/MsaTextArea'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentSettings, Profile } from '~/lib/types'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/personalization'

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.navPersonalization, t.settings.title) }]
}

export default function PersonalizationSettings() {
  const { t } = useT()
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [settings, setSettings] = useState<AgentSettings | null>(null)

  useEffect(() => {
    api.getInstruction('global').then((r) => {
      setContent(r.content)
      setLoaded(true)
    })
    api.getProfile().then(setProfile)
    api.getAgentSettings().then(setSettings)
  }, [])

  const saveInstruction = async () => {
    if (!loaded) return
    try {
      await api.putInstruction('global', content)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    }
  }

  const saveProfile = async (patch: Partial<Profile>) => {
    try {
      const next = await api.putProfile(patch)
      setProfile(next)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    }
  }

  const updateSettings = async (patch: Partial<AgentSettings>) => {
    if (!settings) return
    try {
      const next = await api.putAgentSettings({ ...settings, ...patch })
      setSettings(next)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    }
  }

  return (
    <div className="space-y-8">
      {/* Personalization instructions */}
      <section>
        <div className="mb-3 text-base font-semibold text-msa-text-1">
          {t.personalization.tabInstructions}
        </div>
        <MsaTextArea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onBlur={saveInstruction}
          placeholder={t.settings.personalizationDesc}
          autoSize={{ minRows: 8, maxRows: 8 }}
        />
      </section>

      {/* User profile */}
      <section>
        <div className="mb-4 text-base font-semibold text-msa-text-1">
          {t.personalization.tabProfile}
        </div>
        <div className="space-y-5">
          <div>
            <div className="mb-1.5 text-sm text-msa-text-1">
              {t.profile.callsLabel}
            </div>
            <Input
              value={profile?.agent_calls_user ?? ''}
              placeholder={t.profile.callsPlaceholder}
              onChange={(e) =>
                setProfile(
                  profile
                    ? { ...profile, agent_calls_user: e.target.value }
                    : null
                )
              }
              onBlur={() =>
                profile &&
                saveProfile({ agent_calls_user: profile.agent_calls_user })
              }
            />
          </div>
          <div>
            <div className="mb-1.5 text-sm text-msa-text-1">
              {t.profile.descLabel}
            </div>
            <MsaTextArea
              value={profile?.description ?? ''}
              placeholder={t.profile.descPlaceholder}
              autoSize={{ minRows: 3, maxRows: 8 }}
              onChange={(e) =>
                setProfile(
                  profile ? { ...profile, description: e.target.value } : null
                )
              }
              onBlur={() =>
                profile && saveProfile({ description: profile.description })
              }
            />
          </div>
        </div>
      </section>

      {/* Memory settings */}
      <section>
        <div className="mb-4 text-base font-semibold text-msa-text-1">
          {t.personalization.tabMemory}
        </div>
        <div className="-mt-2 mb-4 text-xs text-msa-text-3">
          {t.personalization.memorySectionDesc}
        </div>
        <div className="space-y-5">
          <div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-msa-text-2">
                {t.personalization.memoryDefaultLabel}
              </span>
              <MsaSwitch
                checked={settings?.default_memory_enabled}
                onChange={(v) => updateSettings({ default_memory_enabled: v })}
              />
            </div>
            <div className="mt-1.5 text-xs text-msa-text-3">
              {t.personalization.memoryDefaultDesc}
            </div>
          </div>
          <div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-msa-text-2">
                {t.personalization.memoryBackendLabel}
              </span>
              <Radio.Group
                value={settings?.default_memory_backend}
                onChange={(e) =>
                  updateSettings({ default_memory_backend: e.target.value })
                }
              >
                <Radio value="file">{t.personalization.backendFile}</Radio>
                <Radio value="vector">{t.personalization.backendVector}</Radio>
              </Radio.Group>
            </div>
            <div className="mt-1.5 text-xs text-msa-text-3">
              {t.personalization.memoryBackendDesc}
            </div>
          </div>

          {/* Vector defaults (extraction / embedding / recall) — gated on the
              default backend: under defaults-only semantics these rows only
              pre-fill projects created as vector; the modal remains the full
              per-project surface. */}
          {settings?.default_memory_backend === 'vector' && settings && (
            <MemoryModelConfig
              value={settings as MemoryModelValue}
              onChange={(patch) => updateSettings(patch)}
            />
          )}
        </div>
      </section>
    </div>
  )
}
