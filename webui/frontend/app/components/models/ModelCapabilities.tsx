import { Tooltip } from 'antd'
import { useT, type Dict } from '~/lib/i18n'
import type { GenerationDefaults, Model } from '~/lib/types'

export function effortLabel(effort: string, t: Dict): string {
  const labels = t.modelsAdmin.effortLabels
  return Object.hasOwn(labels, effort)
    ? labels[effort as keyof typeof labels]
    : effort
}

export function thinkingLabel(defaults: GenerationDefaults | null | undefined, t: Dict): string {
  if (!defaults) return t.modelsAdmin.unknown
  if (defaults.raw_override) return t.modelsAdmin.thinkingAdvanced
  if (defaults.reasoning === false) return t.modelsAdmin.thinkingUnsupported
  if (defaults.reasoning === true && defaults.reasoning_control === 'none') {
    return t.modelsAdmin.thinkingFixed
  }
  return effortLabel(defaults.effort, t)
}

export function thinkingHint(defaults: GenerationDefaults | null | undefined, t: Dict): string {
  if (!defaults) return t.modelsAdmin.thinkingUnknown
  if (defaults.configuration_error) return t.modelsAdmin.configurationError.replace('{error}', defaults.configuration_error)
  if (defaults.reasoning === false) return t.modelsAdmin.thinkingUnsupportedHint
  if (defaults.reasoning === true && defaults.reasoning_control === 'none') {
    return t.modelsAdmin.thinkingFixedHint
  }
  if (defaults.reasoning_control === 'budget') return t.modelsAdmin.thinkingBudgetHint
  if (!defaults.effort_options.length) return t.modelsAdmin.thinkingUnknown
  return t.modelsAdmin.thinkingOptionsHint
}

/** Small, read-only summary; capabilities never imply extra upload transports. */
export function ModelCapabilities({ model }: { model: Model }) {
  const { t, lang } = useT()
  const format = (value: number | null | undefined) =>
    value == null ? t.modelsAdmin.unknown : value.toLocaleString(lang)
  const limit = model.catalog?.context_limit ?? model.context_budget?.model_context_limit
  const vision = effortLabel(model.effective_supports_vision ? 'on' : 'off', t)
  const automatic = model.supports_vision == null
  const context = [
    t.modelsAdmin.contextModelLimit.replace('{tokens}', format(limit)),
    t.modelsAdmin.contextBudget.replace('{tokens}', format(model.context_budget?.context_limit))
  ].join(' · ')
  const defaults = model.generation_defaults
  const reasoning = defaults?.raw_override
    ? t.modelsAdmin.thinkingRawOverride
    : thinkingHint(defaults, t)

  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] leading-[18px] text-msa-text-3">
      <Tooltip title={context} trigger={['hover', 'focus']}>
        <span tabIndex={0}>
          {t.modelsAdmin.rowContext.replace('{tokens}', format(model.context_budget?.context_limit))}
        </span>
      </Tooltip>
      <span>
        {t.modelsAdmin.rowVision.replace('{value}', vision)}
        {automatic ? ` (${t.modelsAdmin.effortLabels.auto})` : ''}
      </span>
      <Tooltip title={reasoning} trigger={['hover', 'focus']}>
        <span tabIndex={0}>
          {t.modelsAdmin.rowThinking.replace('{value}', thinkingLabel(defaults, t))}
        </span>
      </Tooltip>
    </div>
  )
}
