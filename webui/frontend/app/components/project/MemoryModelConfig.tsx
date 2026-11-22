import { AutoComplete, Button, InputNumber, Radio, Select } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api } from '~/lib/api'
import { useOnModelsChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { MemoryModelCheckResult, MemoryProviderOption, Model, Provider } from '~/lib/types'

/** The per-project (or default) memory-model group, API field names. */
export interface MemoryModelValue {
  memory_llm_provider_id: string | null
  memory_llm_model: string | null
  memory_embed_mode: 'provider' | 'local'
  memory_embed_provider_id: string | null
  memory_embed_model: string | null
  memory_recall_top_k: number | null
}

export const MEMORY_MODEL_DEFAULTS: MemoryModelValue = {
  memory_llm_provider_id: null,
  memory_llm_model: null,
  memory_embed_mode: 'provider',
  memory_embed_provider_id: null,
  memory_embed_model: null,
  memory_recall_top_k: null
}

/** Which memory-model fields are invalid for submission. */
export interface MemoryModelErrors {
  /** "Specific provider" chosen for fact extraction but no model picked. */
  llmModel?: boolean
  /** "Specific provider" chosen for embedding but no model entered. */
  embedModel?: boolean
}

/** Validate the group before submit. Both "specific provider" rows require a
 * model — "follow conversation" needs nothing, and "local (offline)" carries no
 * model field. */
export function memoryModelErrors(value: MemoryModelValue): MemoryModelErrors {
  const errors: MemoryModelErrors = {}
  if (value.memory_llm_provider_id && !value.memory_llm_model)
    errors.llmModel = true
  // Custom embedding = provider mode with a chosen provider; that provider's
  // model must be named (there is no "leave blank for default" anymore).
  if (
    value.memory_embed_mode === 'provider' &&
    (!value.memory_embed_provider_id || !value.memory_embed_model?.trim())
  )
    errors.embedModel = true
  return errors
}

interface Props {
  value: MemoryModelValue
  onChange: (patch: Partial<MemoryModelValue>) => void
  /** Fields to flag as invalid (set by the parent on a failed submit). */
  errors?: MemoryModelErrors
}

/** Keep typing local: settings auto-save only a committed model id. */
function ModelInput({ value, onCommit, options, invalid, refresh }: {
  value: string | null
  onCommit: (value: string | null) => void
  options: { value: string; label?: string }[]
  invalid?: boolean
  refresh: () => void
}) {
  const { t } = useT()
  const [draft, setDraft] = useState(value ?? '')
  const focused = useRef(false)
  useEffect(() => {
    if (!focused.current) setDraft(value ?? '')
  }, [value])
  return <AutoComplete
    size="small"
    className="min-w-48"
    value={draft}
    options={options}
    status={invalid ? 'error' : undefined}
    placeholder={t.personalization.memoryModelPlaceholder}
    onChange={setDraft}
    onFocus={() => { focused.current = true; refresh() }}
    onBlur={() => {
      focused.current = false
      const next = draft.trim() || null
      if (next !== value) onCommit(next)
    }}
    onSelect={(next) => { setDraft(next); onCommit(next) }}
    showSearch={{ filterOption: (input, option) =>
      (option?.value ?? '').toLowerCase().includes(input.toLowerCase()) }}
  />
}

/**
 * Vector-memory model rows (extraction model / embedding source / recall
 * count) — ONE implementation shared by the settings page (edits the
 * new-project defaults) and the project modal (edits the project's own,
 * materialized copy). Renders nothing meaningful for the file backend, so
 * callers only mount it when the vector backend is selected.
 */
export function MemoryModelConfig({ value, onChange, errors }: Props) {
  const { t } = useT()
  const [providers, setProviders] = useState<Provider[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [availability, setAvailability] = useState<MemoryProviderOption[]>([])
  const [loadFailed, setLoadFailed] = useState(false)
  const [check, setCheck] = useState<MemoryModelCheckResult | null>(null)
  const [checkFailed, setCheckFailed] = useState(false)
  const [checking, setChecking] = useState(false)
  const alive = useRef(false)
  const sequence = useRef(0)
  const request = useRef<AbortController | null>(null)
  const refresh = useCallback(() => {
    const seq = ++sequence.current
    Promise.all([api.listProviders(), api.listModels(), api.listMemoryProviders()])
      .then(([ps, ms, info]) => {
        if (!alive.current || seq !== sequence.current) return
        setProviders(ps.filter((p) => p.enabled))
        setModels(ms)
        setAvailability(info)
        setLoadFailed(false)
      })
      .catch(() => {
        if (alive.current && seq === sequence.current) setLoadFailed(true)
      })
  }, [])
  useOnModelsChanged(refresh)

  useEffect(() => {
    alive.current = true
    refresh()
    window.addEventListener('focus', refresh)
    return () => {
      alive.current = false
      sequence.current++
      request.current?.abort()
      window.removeEventListener('focus', refresh)
    }
  }, [refresh])
  const configKey = JSON.stringify([
    value.memory_llm_provider_id, value.memory_llm_model,
    value.memory_embed_mode, value.memory_embed_provider_id, value.memory_embed_model
  ])
  useEffect(() => {
    request.current?.abort()
    setChecking(false)
    setCheck(null)
    setCheckFailed(false)
  }, [configKey])
  const verify = async () => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setChecking(true)
    setCheckFailed(false)
    try {
      const result = await api.checkMemoryModels({ ...value, probe: true }, controller.signal)
      if (!controller.signal.aborted) setCheck(result)
    } catch {
      if (!controller.signal.aborted) setCheckFailed(true)
    } finally {
      if (!controller.signal.aborted) setChecking(false)
    }
  }

  const providerOptions = useMemo(
    () => providers.map((p) => ({ value: p.id, label: p.name || p.id })),
    [providers]
  )

  // Normalize a value saved before this row lost its "follow" option (or seeded
  // from such defaults): provider mode has to name a provider, otherwise saving
  // the form re-creates the follow behaviour. Projects whose store already
  // exists arrive pinned to it by the server; this only fills the rest.
  useEffect(() => {
    if (
      value.memory_embed_mode !== 'local' &&
      !value.memory_embed_provider_id &&
      providers.length
    ) {
      onChange({ memory_embed_provider_id: providers[0].id })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, value.memory_embed_mode, value.memory_embed_provider_id])
  const modelOptionsFor = (providerId: string | null) =>
    models
      .filter((m) => m.provider_id === providerId && m.purpose !== 'embedding')
      .map((m) => ({ value: m.name, label: m.display_name || m.name }))
  const embeddingOptions = (availability.find((p) => p.id === value.memory_embed_provider_id)
    ?.embedding_models ?? []).map((name) => ({ value: name }))
  const missingCredentials = availability.some((p) =>
    !p.credentials_available && (p.id === value.memory_llm_provider_id ||
      (value.memory_embed_mode === 'provider' && p.id === value.memory_embed_provider_id)))

  const llmChoice = value.memory_llm_provider_id ? 'custom' : 'follow'
  // Two choices only. "Follow the conversation provider" is deliberately gone:
  // the conversation provider is a GLOBAL setting, so an embedder that follows
  // it changes under a project whenever the user switches models elsewhere —
  // which invalidates that project's vector store and asks for a re-embed the
  // user never asked for. The extraction model above may still follow, because
  // nothing is persisted in its vector space.
  const embedChoice = value.memory_embed_mode === 'local' ? 'local' : 'custom'

  return (
    <div className="space-y-4">
      <div className="text-xs text-msa-text-3">
        {t.personalization.memoryDirectInput}{' '}
        <Link to="/settings/models" target="_blank" rel="noreferrer">
          {t.personalization.memoryConfigureProviders}
        </Link>
        {loadFailed && <div role="alert">{t.personalization.memoryCatalogFailed}</div>}
        {missingCredentials && <div role="alert" className="text-msa-text-danger">
          {t.personalization.memoryCredentialsMissing}
        </div>}
      </div>
      {/* Fact-extraction model — which LLM turns conversation into memory rows. */}
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-msa-text-2">
            {t.personalization.memoryLlmLabel}
          </span>
          <Radio.Group
            value={llmChoice}
            onChange={(e) =>
              onChange(
                e.target.value === 'follow'
                  ? { memory_llm_provider_id: null, memory_llm_model: null }
                  : { memory_llm_provider_id: providers[0]?.id ?? null }
              )
            }
          >
            <Radio value="follow">
              {t.personalization.followConversationModel}
            </Radio>
            <Radio value="custom">{t.personalization.specificProvider}</Radio>
          </Radio.Group>
          {llmChoice === 'custom' && (
            <>
              <Select
                size="small"
                className="min-w-36"
                value={value.memory_llm_provider_id ?? undefined}
                options={providerOptions}
                onChange={(v) =>
                  onChange({
                    memory_llm_provider_id: v,
                    memory_llm_model: null
                  })
                }
              />
              <ModelInput
                key={`llm:${value.memory_llm_provider_id}`}
                invalid={errors?.llmModel}
                value={value.memory_llm_model}
                options={modelOptionsFor(value.memory_llm_provider_id)}
                onCommit={(v) => onChange({ memory_llm_model: v })}
                refresh={refresh}
              />
              {errors?.llmModel && (
                <span className="w-full text-xs text-msa-text-danger">
                  {t.personalization.memoryModelRequired}
                </span>
              )}
            </>
          )}
        </div>
        <div className="mt-1.5 text-xs text-msa-text-3">
          {t.personalization.memoryLlmDesc}
        </div>
      </div>

      {/* Embedding model — provider (follow/custom) or the local offline model. */}
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-msa-text-2">
            {t.personalization.memoryEmbedLabel}
          </span>
          <Radio.Group
            value={embedChoice}
            onChange={(e) => {
              if (e.target.value === 'custom')
                onChange({
                  memory_embed_mode: 'provider',
                  // Never save "provider mode, no provider": that is the
                  // follow-the-global-setting behaviour under another name.
                  memory_embed_provider_id:
                    value.memory_embed_provider_id ?? providers[0]?.id ?? null
                })
              else
                onChange({
                  memory_embed_mode: 'local',
                  memory_embed_provider_id: null,
                  memory_embed_model: null
                })
            }}
          >
            <Radio value="custom">{t.personalization.specificProvider}</Radio>
            <Radio value="local">{t.personalization.embedLocal}</Radio>
          </Radio.Group>
          {embedChoice === 'custom' && (
            <>
              <Select
                size="small"
                className="min-w-36"
                value={value.memory_embed_provider_id ?? undefined}
                options={providerOptions}
                onChange={(v) =>
                  onChange({
                    memory_embed_provider_id: v,
                    memory_embed_model: null
                  })
                }
              />
              <ModelInput
                key={`embedding:${value.memory_embed_provider_id}`}
                invalid={errors?.embedModel}
                value={value.memory_embed_model}
                options={embeddingOptions}
                onCommit={(v) => onChange({ memory_embed_model: v })}
                refresh={refresh}
              />
              {errors?.embedModel && (
                <span className="w-full text-xs text-msa-text-danger">
                  {t.personalization.memoryEmbedModelRequired}
                </span>
              )}
            </>
          )}
        </div>
        <div className="mt-1.5 text-xs text-msa-text-3">
          {embedChoice === 'local'
            ? t.personalization.embedLocalDesc
            : t.personalization.memoryEmbedDesc}
        </div>
      </div>

      {/* Recall count — how many recalled memories are injected per turn. */}
      <div className="space-y-1 text-xs text-msa-text-3">
        <Button size="small" loading={checking} onClick={verify}>
          {t.personalization.memoryVerify}
        </Button>
        <div>{check?.verified ? t.personalization.memoryVerified : t.personalization.memoryUnverified}</div>
        {check?.errors.map((error) => <div key={error.code} role="alert" className="text-msa-text-danger">{error.message}</div>)}
        {checkFailed && <div role="alert">{t.personalization.memoryCheckFailed}</div>}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm text-msa-text-2">
          {t.personalization.memoryRecallLabel}
        </span>
        <InputNumber
          size="small"
          min={1}
          max={50}
          placeholder="10"
          value={value.memory_recall_top_k ?? undefined}
          onChange={(v) =>
            onChange({ memory_recall_top_k: typeof v === 'number' ? v : null })
          }
        />
        <span className="text-xs text-msa-text-3">
          {t.personalization.memoryRecallDesc}
        </span>
      </div>
    </div>
  )
}
