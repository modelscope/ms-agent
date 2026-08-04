import { Button, Popconfirm, Select, Tooltip } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { AddProviderModal } from '~/components/models/AddProviderModal'
import { ModelEditModal } from '~/components/models/ModelEditModal'
import { EmptyState } from '~/components/common/EmptyState'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentSettings, Model, Provider } from '~/lib/types'
import IconEdit from '~/assets/icons/edit.svg?react'
import IconDelete from '~/assets/icons/delete.svg?react'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/models'
import AddIcon from '~/assets/icons/add.svg?react'

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.navModels, t.settings.title) }]
}

export default function ModelsSettings() {
  const { t } = useT()
  // null = not loaded yet (skeleton), [] = genuinely no providers (empty
  // state). Collapsing the two would flash "no providers" on every visit.
  const [providers, setProviders] = useState<Provider[] | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null)

  // Provider add/edit share one modal: null = closed, { provider: null } = add,
  // { provider } = edit.
  const [providerModal, setProviderModal] = useState<{
    provider: Provider | null
  } | null>(null)
  const [modelEdit, setModelEdit] = useState<{
    provider: Provider
    model: Model | null
  } | null>(null)

  const refresh = () =>
    Promise.all([
      api.listProviders(),
      api.listModels(),
      api.getAgentSettings()
    ]).then(([ps, ms, s]) => {
      setProviders(ps)
      setModels(ms)
      setSettings(s)
      // Default-select the first provider when nothing is selected.
      setActiveProviderId((prev) => prev ?? ps[0]?.id ?? null)
    })

  useEffect(() => {
    refresh()
  }, [])

  const activeProvider = useMemo(
    () => providers?.find((p) => p.id === activeProviderId) ?? null,
    [providers, activeProviderId]
  )

  const providerModels = useMemo(
    () => models.filter((m) => m.provider_id === activeProviderId),
    [models, activeProviderId]
  )

  const updateSettings = async (patch: Partial<AgentSettings>) => {
    if (!settings) return
    const next = await api.putAgentSettings({ ...settings, ...patch })
    setSettings(next)
  }

  const selectDefaultProvider = (providerId: string) => {
    setSettings((prev) =>
      prev
        ? {
            ...prev,
            default_provider_id: providerId,
            default_model_id: null
          }
        : prev
    )
  }

  const defaultModelOptions = useMemo(
    () =>
      models
        .filter((m) =>
          settings?.default_provider_id
            ? m.provider_id === settings.default_provider_id
            : true
        )
        .map((m) => ({
          value: m.id,
          label: m.display_name || m.name
        })),
    [models, settings?.default_provider_id]
  )

  return (
    <div className="flex h-full flex-col">
      {/* Default model picker */}
      <section className="mb-6 shrink-0">
        <div className="mb-3 text-base font-semibold text-msa-text-1">
          {t.settings.modelDefault}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-msa-text-2">
              {t.settings.provider}
            </div>
            <Select
              value={settings?.default_provider_id ?? undefined}
              onChange={selectDefaultProvider}
              options={(providers ?? []).map((p) => ({
                value: p.id,
                label: p.name,
                disabled: !p.enabled
              }))}
              className="w-full"
              placeholder="—"
            />
          </div>
          <div>
            <div className="mb-1 text-xs text-msa-text-2">
              {t.settings.model}
            </div>
            <Select
              value={settings?.default_model_id ?? undefined}
              onChange={(v) => updateSettings({ default_model_id: v })}
              options={defaultModelOptions}
              className="w-full"
              placeholder="—"
              disabled={!settings?.default_provider_id}
            />
          </div>
        </div>
      </section>

      {/* Providers admin — two-pane layout */}
      <section className="flex min-h-0 flex-1 flex-col">
        <div className="mb-3 shrink-0 text-base font-semibold text-msa-text-1">
          {t.settings.providers}
        </div>

        {/* The two-pane shell ALWAYS renders (it is the page's default look);
            emptiness is per pane — a small empty state in the provider list
            (with "add provider" still available below) and one in the detail
            pane — never a lone full-area empty state. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-msa-line-1 md:flex-row">
          {/* Left: providers list */}
          <aside className="flex max-h-[240px] w-full shrink-0 flex-col border-b border-msa-line-1 md:max-h-none md:w-[280px] md:border-b-0 md:border-r">
            <div className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
              {providers === null ? (
                <DeferredSkeleton rows={8} className="px-1 py-2" />
              ) : providers.length === 0 ? (
                <EmptyState
                  size="sm"
                  description={t.modelsAdmin.noProviders}
                  className="!py-8"
                />
              ) : (
                providers.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setActiveProviderId(p.id)}
                    className={`flex w-full cursor-pointer items-center gap-2 rounded-[10px] border-0 px-3.5 py-3 text-left text-sm font-medium transition-all ${
                      activeProviderId === p.id
                        ? 'bg-msa-fill-2 text-msa-text-1'
                        : 'bg-transparent text-msa-text-1 hover:bg-msa-fill-2'
                    }`}
                  >
                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                    {p.kind === 'builtin' && (
                      <span className="shrink-0 rounded bg-msa-purple-6/8 px-2 py-0.5 text-xs text-msa-purple-6">
                        {t.modelsAdmin.builtinBadge}
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
            <div
              className="flex cursor-pointer items-center justify-center gap-1.5 border-t border-msa-line-1 py-3.5 text-sm text-msa-purple-6 transition-opacity hover:opacity-80"
              onClick={() => setProviderModal({ provider: null })}
            >
              <AddIcon className="h-4 w-4" />
              <span>{t.modelsAdmin.addProvider}</span>
            </div>
          </aside>

          {/* Right: provider detail + models */}
          <div className="min-w-0 flex-1 overflow-y-auto px-7 py-6">
            {activeProvider ? (
              <ProviderDetail
                provider={activeProvider}
                models={providerModels}
                rawModels={providerModels}
                onAddModel={() =>
                  setModelEdit({ provider: activeProvider, model: null })
                }
                onConfigure={() => setProviderModal({ provider: activeProvider })}
                onDelete={async () => {
                  try {
                    await api.deleteProvider(activeProvider.id)
                    setActiveProviderId(null)
                    refresh()
                  } catch {
                    // API errors surface via the global toast.
                  }
                }}
                onEditModel={(m) =>
                  setModelEdit({ provider: activeProvider, model: m })
                }
                onDeleteModel={async (m) => {
                  try {
                    await api.deleteModel(m.id)
                    refresh()
                  } catch {
                    // API errors surface via the global toast.
                  }
                }}
              />
            ) : providers === null ? (
              <DeferredSkeleton rows={6} />
            ) : (
              <EmptyState description={t.modelsAdmin.selectProvider} />
            )}
          </div>
        </div>
      </section>

      <AddProviderModal
        open={!!providerModal}
        provider={providerModal?.provider ?? null}
        onClose={() => setProviderModal(null)}
        onSaved={(p) => {
          setProviderModal(null)
          setActiveProviderId(p.id)
          refresh()
        }}
      />
      <ModelEditModal
        open={!!modelEdit}
        defaultProvider={modelEdit?.provider ?? null}
        model={modelEdit?.model ?? null}
        providers={providers ?? []}
        onClose={() => setModelEdit(null)}
        onSaved={() => {
          setModelEdit(null)
          refresh()
        }}
      />
    </div>
  )
}

function ProviderDetail({
  provider,
  models,
  rawModels,
  onAddModel,
  onConfigure,
  onDelete,
  onEditModel,
  onDeleteModel
}: {
  provider: Provider
  models: Model[]
  rawModels: Model[]
  onAddModel: () => void
  onConfigure: () => void
  onDelete: () => void
  onEditModel: (m: Model) => void
  onDeleteModel: (m: Model) => void
}) {
  const { t } = useT()

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      {/* Provider header */}
      <div className="mb-3 flex items-center gap-3">
        <div className="min-w-0 flex-1 truncate text-lg font-semibold text-msa-text-1">
          {provider.name}
        </div>
        <Button
          size="small"
          icon={<IconEdit className="h-4 w-4" />}
          onClick={onConfigure}
        >
          {t.resources.edit}
        </Button>
        {provider.kind !== 'builtin' && (
          <Popconfirm
            title={t.modelsAdmin.deleteProviderConfirm}
            okType="danger"
            okText={t.modelsAdmin.confirm}
            cancelText={t.modelsAdmin.cancel}
            onConfirm={onDelete}
          >
            <Button
              size="small"
              danger
              icon={<IconDelete className="h-4 w-4" />}
            >
              {t.modelsAdmin.deleteProvider}
            </Button>
          </Popconfirm>
        )}
      </div>
      <div className="mb-6 flex flex-col gap-1.5">
        <div className="text-[13px] leading-5 text-msa-text-3">
          {t.modelsAdmin.baseUrl}：{provider.base_url || '—'}
        </div>
        <div className="text-[13px] leading-5 text-msa-text-3">
          {t.modelsAdmin.protocol}：
          {provider.protocol === 'openai'
            ? t.modelsAdmin.protocolOpenAI
            : t.modelsAdmin.protocolAnthropic}
        </div>
      </div>

      {/* Models section */}
      <div className="mb-3 text-sm font-medium text-msa-text-1">
        {t.modelsAdmin.modelCount.replace('{count}', String(rawModels.length))}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {models.length === 0 ? (
          <EmptyState description={t.modelsAdmin.noModels} />
        ) : (
          models.map((m) => (
            <div
              key={m.id}
              className="flex items-center gap-3 rounded-[10px] bg-msa-fill-1 px-4 py-3.5"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium leading-5 text-msa-text-1">
                  {m.display_name || m.name}
                </div>
                <div className="mt-0.5 truncate text-xs leading-[18px] text-msa-text-3">
                  {m.name}
                </div>
              </div>
              <Tooltip title={t.modelsAdmin.editModel}>
                <IconEdit
                  className="h-[18px] w-[18px] shrink-0 cursor-pointer text-msa-text-3 transition-colors hover:text-msa-purple-6"
                  onClick={() => onEditModel(m)}
                />
              </Tooltip>
              <Popconfirm
                title={t.modelsAdmin.confirmDelete}
                okType="danger"
                onConfirm={() => onDeleteModel(m)}
              >
                <Tooltip title={t.modelsAdmin.deleteModel}>
                  <IconDelete className="h-[18px] w-[18px] shrink-0 cursor-pointer text-msa-text-3 transition-colors hover:text-msa-purple-6" />
                </Tooltip>
              </Popconfirm>
            </div>
          ))
        )}

        {/* Add model button - inline with model items */}
        <div
          className="flex cursor-pointer items-center justify-center gap-1.5 rounded-[10px] border border-dashed border-msa-line-1 px-4 py-[18px] text-sm text-msa-text-brand1 transition-colors hover:border-msa-line-3"
          onClick={onAddModel}
        >
          <AddIcon className="h-4 w-4" />
          <span>{t.modelsAdmin.addModel}</span>
        </div>
      </div>
    </div>
  )
}
