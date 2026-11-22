import { App, Button, Input, Select } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Provider } from '~/lib/types'

export function DecisionModelSettings() {
  const { t } = useT()
  const { message } = App.useApp()
  const [providers, setProviders] = useState<Provider[]>([])
  const [provider, setProvider] = useState<string>()
  const [model, setModel] = useState('decision-model-preview')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  useEffect(() => {
    let active = true
    void Promise.all([api.listProviders(), api.getAgentSettings()]).then(([list, settings]) => {
      if (!active) return
      setProviders(list)
      setProvider(settings.decision_provider_id ?? undefined)
      setModel(settings.decision_model ?? 'decision-model-preview')
    }).catch(() => {})
    return () => { active = false }
  }, [])
  const save = async () => {
    setSaving(true)
    try {
      await api.putAgentSettings({ decision_provider_id: provider, decision_model: model.trim() })
      void message.success(t.decisionMode.saved)
    } finally { setSaving(false) }
  }
  const test = async () => {
    if (!provider) return
    setTesting(true)
    try {
      await api.testDecisionConnection(provider, model.trim())
      void message.success(t.decisionMode.connected)
    } finally { setTesting(false) }
  }
  return <section className="space-y-3">
    <h2 className="text-base font-semibold text-msa-text-1">{t.decisionMode.settingsTitle}</h2>
    <p className="text-sm text-msa-text-3">{t.decisionMode.settingsDescription}</p>
    <div className="flex flex-wrap items-center gap-3">
      <Select aria-label={t.decisionMode.provider} className="min-w-[220px]" value={provider}
        placeholder={t.decisionMode.provider} onChange={setProvider}
        options={providers.filter(p => p.enabled).map(p => ({ value: p.id, label: p.name }))} />
      <Input aria-label={t.decisionMode.model} className="!w-[260px]" value={model} onChange={event => setModel(event.target.value)} />
      <Button disabled={!provider || !model.trim()} loading={saving} onClick={() => { void save().catch(() => {}) }}>{t.decisionMode.save}</Button>
      <Button disabled={!provider || !model.trim()} loading={testing} onClick={() => { void test().catch(() => {}) }}>{t.decisionMode.test}</Button>
    </div>
  </section>
}
