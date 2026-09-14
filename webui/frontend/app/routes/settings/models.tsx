import { Button, Popconfirm, Select, Tooltip } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { AddProviderModal } from '~/components/models/AddProviderModal'
import { ModelEditModal } from '~/components/models/ModelEditModal'
import { ProviderTags } from '~/components/models/ProviderTags'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
import { KeyStatusTag } from '~/components/common/KeyStatus'
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
  const [searchParams] = useSearchParams()
  // null = not loaded yet (skeleton), [] = genuinely no providers (empty
  // state). Collapsing the two would flash "no providers" on every visit.
  const [providers, setProviders] = useState<Provider[] | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  // `?provider=` lets a caller open this page on the provider it was talking
  // about — the composer's model picker sends the one whose list it found empty.
  // A seed only: the selection is the user's from here on.
  const [activeProviderId, setActiveProviderId] = useState<string | null>(() =>
    searchParams.get('provider')
  )

  // Provider add/edit share one modal: null = closed, { provider: null } = add,
  // { provider } = edit.
  const [providerModal, setProviderModal] = useState<{
    provider: Provider | null
  } | null>(null)
  const [modelEdit, setModelEdit] = useState<{
    provider: Provider
    model: Model | null
    /** Opened from the default-model picker: the model it creates is the one the
     *  user was trying to pick, so it becomes the selection on save. */
    asDefault?: boolean
  } | null>(null)
  // Controlled so the empty state's "add model" button can close the panel:
  // the select popup outranks the modal mask, and would otherwise float on top
  // of the dialog it just opened.
  const [defaultModelOpen, setDefaultModelOpen] = useState(false)

  const refresh = () =>
    Promise.all([
      api.listProviders(),
      api.listModels(),
      api.getAgentSettings()
    ])
      .then(([ps, ms, s]) => {
        setProviders(ps)
        setModels(ms)
        setSettings(s)
        // Default-select the first provider when nothing is selected. A seed
        // naming a provider this instance does not have is dropped here rather
        // than left selected, which would render as a blank detail pane.
        setActiveProviderId((prev) =>
          prev && ps.some((p) => p.id === prev) ? prev : (ps[0]?.id ?? null)
        )
      })
      // `null` gates the skeletons on this page, so a failure has to settle the
      // lists to `[]` or they stay skeletons for good. `Promise.all` means any
      // one of the three failing takes the other two down with it — the page
      // then reads as empty rather than broken, which the toast has to explain.
      // `settings` stays `null`: every read of it is optional-chained.
      .catch(() => {
        setProviders([])
        setModels([])
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

  const defaultProvider = useMemo(
    () => providers?.find((p) => p.id === settings?.default_provider_id) ?? null,
    [providers, settings?.default_provider_id]
  )

  const updateSettings = async (patch: Partial<AgentSettings>) => {
    if (!settings) return
    const next = await api.putAgentSettings(patch)
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

  const addDefaultModel = () => {
    if (!defaultProvider) return
    setDefaultModelOpen(false)
    setModelEdit({ provider: defaultProvider, model: null, asDefault: true })
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

  // The settings pointer survives deleting the model it names, so it can address
  // a model that no longer exists. Resolve it against the options and treat an
  // unresolvable pointer as "nothing selected".
  const resolvedDefaultModelId = useMemo(
    () =>
      defaultModelOptions.some((o) => o.value === settings?.default_model_id)
        ? (settings?.default_model_id ?? undefined)
        : undefined,
    [defaultModelOptions, settings?.default_model_id]
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
              // The closed box shows the name alone; the tags (built-in pill,
              // key glyph) ride the dropdown OPTIONS, where the user is choosing
              // and the "is this ready to use" signal actually helps. Looked up
              // by id because the option only carries value + label. The name
              // span does NOT grow (no flex-1) so the tags hug the text; it only
              // shrinks + truncates when the name is too long to fit.
              optionRender={(option) => {
                const p = (providers ?? []).find((x) => x.id === option.value)
                return (
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 truncate">{option.label}</span>
                    {p && <ProviderTags provider={p} />}
                  </div>
                )
              }}
              className="w-full"
              placeholder="—"
            />
          </div>
          <div>
            <div className="mb-1 text-xs text-msa-text-2">
              {t.settings.model}
            </div>
            <Select
              // Only show a value the options can label. The active model can
              // point at a DELETED model (settings keeps the pointer), and antd
              // then renders the raw value — a base64 model id — as the label.
              // Falling back to the placeholder says "nothing selected", which is
              // what an unresolvable pointer means.
              value={resolvedDefaultModelId}
              onChange={(v) => updateSettings({ default_model_id: v })}
              options={defaultModelOptions}
              open={defaultModelOpen}
              onOpenChange={setDefaultModelOpen}
              // A provider with no models leaves this picker with nothing to
              // offer, and the models list that fixes it is further down the
              // page — behind a provider selection of its own. Adding from here
              // opens the same modal that pane uses, on the provider this
              // picker is already pointed at.
              notFoundContent={
                <EmptyState
                  size="xs"
                  description={t.modelsAdmin.modelsEmpty}
                  action={
                    <EmptyStateAction
                      className="!px-4 !py-1 !text-xs"
                      onClick={addDefaultModel}
                    >
                      {t.modelsAdmin.addModel}
                    </EmptyStateAction>
                  }
                />
              }
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
          {/* Left: providers list.
              Stacked below `md`, where the shell is capped to the viewport and
              every pixel this pane takes is one the models list below it loses.
              192px leaves the rows a ~2.5-row window (44px each): the half row
              peeking at the bottom is what says "scrolls", and picking a provider
              is a short list you visit once, while picking a model is the reason
              you came. Uncapped from `md` up, where the two panes sit side by side
              and the height is no longer shared. */}
          <aside className="flex max-h-[192px] w-full shrink-0 flex-col border-b border-msa-line-1 md:max-h-none md:w-[280px] md:border-b-0 md:border-r">
            {/* stable both-edges: the styled scrollbar reserves a gutter on the
                right only, which would leave the selected-row highlight with a
                wider gap on the right than the left. Mirroring the gutter on
                both edges keeps the row insets symmetric. Horizontal padding is
                dropped from p-3 to px-1 to offset the ~8px gutter, so the total
                inset stays ~12px — the same as the original p-3. */}
            <div
              className="flex flex-1 flex-col gap-1 overflow-y-auto px-1 py-3"
              style={{ scrollbarGutter: 'stable both-edges' }}
            >
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
                    // Long display names truncate visually; the tooltip surfaces
                    // the full text on hover so a clipped label never becomes a
                    // guess. Same pattern as the ModelSelector row.
                    title={p.name}
                    onClick={() => setActiveProviderId(p.id)}
                    className={`flex w-full cursor-pointer items-center gap-2 rounded-[10px] border-0 px-3.5 py-3 text-left text-sm font-medium transition-all ${
                      activeProviderId === p.id
                        ? 'bg-msa-fill-2 text-msa-text-1'
                        : 'bg-transparent text-msa-text-1 hover:bg-msa-fill-2'
                    }`}
                  >
                    <span className="min-w-0 truncate">{p.name}</span>
                    <ProviderTags provider={p} />
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

          {/* Right: provider detail + models.
              Tighter gutters below `md`: at phone widths `px-7` cost 56px of a
              ~340px pane, which pushed the Base URL and protocol lines into two
              rows each and shrank the models list by roughly a card and a half. */}
          <div className="min-w-0 flex-1 overflow-y-auto px-4 py-4 md:px-7 md:py-6">
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
        onSaved={async (m) => {
          const asDefault = modelEdit?.asDefault ?? false
          setModelEdit(null)
          // Coming from the default-model picker, the new model is what the
          // user was there to choose. The provider rides along because picking
          // one is local state until a model is saved with it — the reload
          // below would otherwise restore the previously persisted provider and
          // drop the model out of sight. Awaited, since a concurrent GET can
          // still answer with the pre-save settings.
          if (asDefault) {
            try {
              await updateSettings({
                default_provider_id: m.provider_id,
                default_model_id: m.id
              })
            } catch {
              // API errors surface via the global toast.
            }
          }
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
  // Masked, not plaintext: its emptiness is all the API reveals about the key.
  const hasKey = !!provider.api_key_masked

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      {/* Provider header */}
      <div className="mb-3 flex items-center gap-3">
        <div
          className="min-w-0 flex-1 truncate text-lg font-semibold text-msa-text-1"
          // Same tooltip pattern as the left rail: a truncated title without a
          // tooltip forces users to click into edit to read the full name.
          title={provider.name}
        >
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
        {/* The stored key is never sent back to the client, so without this the
            only way to tell whether one is on file was to open the edit modal.
            Same tag and wording as that modal's field label — it reports the
            same fact, so it should not read as a second, different signal. */}
        <div className="flex items-center gap-1 text-[13px] leading-5 text-msa-text-3">
          {t.modelsAdmin.apiKey}：
          <KeyStatusTag set={hasKey}>
            {hasKey
              ? t.modelsAdmin.apiKeyConfigured
              : t.modelsAdmin.apiKeyMissing}
          </KeyStatusTag>
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
                <div
                  className="truncate text-sm font-medium leading-5 text-msa-text-1"
                  // Both lines can be long: display_name up to 160 chars, the
                  // model id itself often longer than the row can hold.
                  title={m.display_name || m.name}
                >
                  {m.display_name || m.name}
                </div>
                <div
                  className="mt-0.5 truncate text-xs leading-[18px] text-msa-text-3"
                  title={m.name}
                >
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

        {/* Sticky instead of antd Affix: no scroll target to wire up, and a
            short list never scrolls so it just sits inline. The wrapper pulls
            the pane background over the list gap above it (-mt-3 + pt-3 cancel
            out) so rows slide out of sight behind the button. */}
        <div className="sticky bottom-0 -mt-3 bg-msa-fill-0 pt-3">
          <div
            className="flex cursor-pointer items-center justify-center gap-1.5 rounded-[10px] border border-dashed border-msa-line-1 px-4 py-[18px] text-sm text-msa-text-brand1 transition-colors hover:border-msa-line-3"
            onClick={onAddModel}
          >
            <AddIcon className="h-4 w-4" />
            <span>{t.modelsAdmin.addModel}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
