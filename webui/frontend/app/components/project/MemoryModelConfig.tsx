import { InputNumber, Radio, Select } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Model, Provider } from '~/lib/types'

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
    value.memory_embed_provider_id &&
    !value.memory_embed_model
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

  useEffect(() => {
    // Pick among registered providers/models instead of re-entering creds.
    api
      .listProviders()
      .then((p) => setProviders(p.filter((x) => x.enabled)))
      .catch(() => setProviders([]))
    api
      .listModels()
      .then(setModels)
      .catch(() => setModels([]))
  }, [])

  const providerOptions = useMemo(
    () => providers.map((p) => ({ value: p.id, label: p.name || p.id })),
    [providers]
  )
  const modelOptionsFor = (providerId: string | null) =>
    models
      .filter((m) => m.provider_id === providerId)
      .map((m) => ({ value: m.name, label: m.display_name || m.name }))

  const llmChoice = value.memory_llm_provider_id ? 'custom' : 'follow'
  const embedChoice =
    value.memory_embed_mode === 'local'
      ? 'local'
      : value.memory_embed_provider_id
        ? 'custom'
        : 'follow'

  return (
    <div className="space-y-4">
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
              <Select
                size="small"
                className="min-w-48"
                showSearch
                status={errors?.llmModel ? 'error' : undefined}
                placeholder={t.personalization.memoryModelPlaceholder}
                value={value.memory_llm_model ?? undefined}
                options={modelOptionsFor(value.memory_llm_provider_id)}
                onChange={(v) => onChange({ memory_llm_model: v })}
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
              const v = e.target.value
              if (v === 'follow')
                onChange({
                  memory_embed_mode: 'provider',
                  memory_embed_provider_id: null,
                  memory_embed_model: null
                })
              else if (v === 'custom')
                onChange({
                  memory_embed_mode: 'provider',
                  memory_embed_provider_id: providers[0]?.id ?? null
                })
              else
                onChange({
                  memory_embed_mode: 'local',
                  memory_embed_provider_id: null,
                  memory_embed_model: null
                })
            }}
          >
            <Radio value="follow">
              {t.personalization.embedFollowProvider}
            </Radio>
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
              <Select
                size="small"
                className="min-w-48"
                showSearch
                status={errors?.embedModel ? 'error' : undefined}
                placeholder={t.personalization.memoryModelPlaceholder}
                value={value.memory_embed_model ?? undefined}
                options={modelOptionsFor(value.memory_embed_provider_id)}
                onChange={(v) => onChange({ memory_embed_model: v })}
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
