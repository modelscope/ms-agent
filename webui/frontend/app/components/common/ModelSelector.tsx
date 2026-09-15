import { CheckOutlined } from '@ant-design/icons'
import { Popover } from 'antd'
import { Fragment, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { ProviderTags } from '~/components/models/ProviderTags'
import { useT } from '~/lib/i18n'
import type { AgentSettings, Model, Provider } from '~/lib/types'
import { PillButton } from './PillButton'
import { EmptyState, EmptyStateAction } from './EmptyState'
import { DeferredSkeleton } from './DeferredSkeleton'
import './ModelSelector.css'
import JumpIcon from '~/assets/icons/jump.svg?react'
import BackIcon from '~/assets/icons/back.svg?react'

interface ModelSelectorProps {
  /** null while the lists are still loading — the panel then shows a
   * skeleton instead of an "empty" state that isn't true yet. */
  models: Model[] | null
  providers: Provider[] | null
  settings: AgentSettings | null
  onSelectModel: (providerId: string, modelId: string) => void
}

export function ModelSelector({
  models,
  providers,
  settings,
  onSelectModel
}: ModelSelectorProps) {
  const { t } = useT()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null)
  // Below `sm` the two panes cannot both fit: the panel is capped at the viewport
  // (`100vw-32px`), so on a phone the 280px provider column left the models one
  // ~80px — every name clipped to "Qwen/…". There the panel shows ONE pane at a
  // time and the row arrow becomes a real drill-in. Ignored from `sm` up, where
  // CSS shows both panes regardless. Starts at the models pane because that is
  // what the pill was clicked for; its header walks back up to the provider list.
  const [drilled, setDrilled] = useState(true)

  const defaultModel = useMemo(
    () => models?.find((m) => m.id === settings?.default_model_id) ?? null,
    [models, settings]
  )

  // Sync active provider with the current default provider when opening.
  const effectiveProviderId =
    activeProviderId ??
    defaultModel?.provider_id ??
    settings?.default_provider_id ??
    providers?.[0]?.id ??
    null

  const activeProvider = useMemo(
    () => providers?.find((p) => p.id === effectiveProviderId) ?? null,
    [providers, effectiveProviderId]
  )

  const providerModels = useMemo(
    () =>
      (models ?? [])
        .filter((m) => m.provider_id === effectiveProviderId)
        .sort((a, b) =>
          (a.display_name || a.name).localeCompare(b.display_name || b.name)
        ),
    [models, effectiveProviderId]
  )

  const handleSelectModel = (model: Model) => {
    onSelectModel(model.provider_id, model.id)
    setOpen(false)
  }

  /** A provider with no models is a dead end here — models are added in global
   * settings, never from this picker. The provider being browsed rides along in
   * the URL so the page opens on it instead of on its own first one, which is
   * rarely the one the user just found empty. */
  const goAddModels = () => {
    setOpen(false)
    navigate(
      activeProvider
        ? `/settings/models?provider=${encodeURIComponent(activeProvider.id)}`
        : '/settings/models'
    )
  }

  return (
    <Popover
      open={open}
      onOpenChange={(v) => {
        setOpen(v)
        if (!v) setDrilled(true)
      }}
      trigger="click"
      classNames={{
        container: 'p-0'
      }}
      content={
        <div className="flex h-[300px] w-[min(661px,calc(100vw-32px))]">
          {/* Left: providers.
              Fixed width from `sm` up, not shrink-0 alone: without a cap the
              column expands to fit the widest provider name, which squeezes the
              models column (min-w-0 flex-1) down to a few characters. 280px keeps
              common provider names on one line next to their status tags, while
              the row's own `truncate` handles longer canonical or custom names.
              The models column keeps ~380px, still ample for model names.
              Below `sm` it instead spans the full panel and yields the whole
              panel to the models pane once drilled in. */}
          <div
            className={`h-full w-full shrink-0 flex-col gap-1 overflow-y-auto border-msa-line-1 p-[6px] sm:flex sm:w-[280px] sm:border-r ${
              drilled ? 'hidden' : 'flex'
            }`}
          >
            {(providers ?? []).map((p) => {
              const selected = p.id === effectiveProviderId
              return (
                <button
                  key={p.id}
                  type="button"
                  title={p.name}
                  onClick={() => {
                    setActiveProviderId(p.id)
                    setDrilled(true)
                  }}
                  className={`flex w-full cursor-pointer items-center gap-2 rounded-[8px] border-0 px-[10px] py-[13px] text-left text-sm font-medium transition-colors ${
                    selected
                      ? 'bg-msa-fill-4 text-msa-text-brand1'
                      : 'bg-msa-fill-0 text-msa-text-1 hover:bg-msa-fill-4 hover:text-msa-text-brand1'
                  }`}
                >
                  {/* No `flex-1` on the name: it would claim the row's slack and
                      push the tags over to the arrow, reading as if they
                      belonged to it. Shrinking (the flex default) still lets
                      `truncate` cut a long name, and `ml-auto` keeps the arrow
                      pinned right. Same tags as the settings provider list, so
                      "built-in" and "key on file" mean the same thing here. */}
                  <span className="min-w-0 truncate">{p.name}</span>
                  <ProviderTags provider={p} />
                  <JumpIcon className="ml-auto h-[15px] w-[15px] shrink-0 text-msa-text-3" />
                </button>
              )
            })}
          </div>

          {/* Right: models */}
          <div
            className={`h-full min-w-0 flex-1 flex-col sm:flex ${
              drilled ? 'flex' : 'hidden'
            }`}
          >
            {/* The way back up, and the only thing naming the provider these
                models belong to once the list beside them is off screen. Phone
                only — from `sm` up the provider column is right there, and a
                second copy of its name would just repeat it. */}
            {activeProvider && (
              <>
                <button
                  type="button"
                  onClick={() => setDrilled(false)}
                  title={t.modelsAdmin.changeProvider}
                  className="flex shrink-0 cursor-pointer items-center gap-1.5 border-0 bg-msa-fill-0 px-[10px] py-[10px] text-left text-sm font-medium text-msa-text-1 transition-colors hover:text-msa-text-brand1 sm:hidden"
                >
                  <BackIcon className="h-5 w-5 shrink-0" />
                  <span className="min-w-0 truncate">
                    {activeProvider.name}
                  </span>
                </button>
                <div className="h-px shrink-0 bg-msa-line-1 sm:hidden" />
              </>
            )}

            <div className="min-h-0 flex-1 overflow-y-auto p-[6px]">
              {models === null || providers === null ? (
                <DeferredSkeleton rows={5} className="p-2" />
              ) : activeProvider ? (
                providerModels.length === 0 ? (
                  <div className="flex h-full items-center justify-center">
                    <EmptyState
                      size="sm"
                      // The pane is 300px tall and the illustration, copy and
                      // button already fill it — the variant's own vertical
                      // padding on top of that would push the button out of
                      // reach (a centred flex child clips, it does not scroll).
                      className="!py-0"
                      description={t.modelsAdmin.modelsEmpty}
                      action={
                        // Smaller than the full-page empty states this button
                        // was sized for: here it sits in a popover among 12px
                        // rows, where the default pill reads as the loudest
                        // thing on screen.
                        <EmptyStateAction
                          className="!px-4 !py-1 !text-xs"
                          onClick={goAddModels}
                        >
                          {t.modelsAdmin.addModel}
                        </EmptyStateAction>
                      }
                    />
                  </div>
                ) : (
                  <div className="msel-list flex flex-col">
                    {providerModels.map((m, idx) => {
                      const selected = m.id === settings?.default_model_id
                      return (
                        <Fragment key={m.id}>
                          {idx > 0 && (
                            <div className="msel-divider mx-[10px] my-[1px] h-px bg-msa-line-1 transition-opacity" />
                          )}
                          <button
                            type="button"
                            title={m.display_name || m.name}
                            onClick={() => handleSelectModel(m)}
                            className={`flex w-full cursor-pointer items-center justify-between gap-2 rounded-[8px] border-0 px-[10px] py-[13px] text-left text-sm font-medium transition-colors ${
                              selected
                                ? 'msel-selected bg-msa-fill-4 text-msa-text-brand1'
                                : 'bg-msa-fill-0 text-msa-text-1 hover:bg-msa-fill-4'
                            }`}
                          >
                            <span className="flex min-w-0 flex-1 flex-col">
                              <span className="truncate">
                                {m.display_name || m.name}
                              </span>
                              {m.display_name && (
                                <span className="truncate text-xs font-normal text-msa-text-3">
                                  {m.name}
                                </span>
                              )}
                            </span>
                            {selected && (
                              <CheckOutlined className="shrink-0 h-[15px] w-[15px] text-msa-text-brand1" />
                            )}
                          </button>
                        </Fragment>
                      )
                    })}
                  </div>
                )
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-msa-text-3">
                  —
                </div>
              )}
            </div>
          </div>
        </div>
      }
    >
      <PillButton
        open={open}
        icon={
          <span className="h-2 w-2 inline-block rounded-full bg-msa-purple-5" />
        }
      >
        {defaultModel?.display_name ?? t.home.modelUnset}
      </PillButton>
    </Popover>
  )
}
