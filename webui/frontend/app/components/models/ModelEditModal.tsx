import { App, AutoComplete, Form, Input, InputNumber, Modal, Select, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { effortLabel, thinkingHint } from './ModelCapabilities'
import { api } from '~/lib/api'
import { dispatchModelsChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { GenerationDefaults, Model, Provider, ReasoningEffort } from '~/lib/types'

function parseParams(json: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(json || '{}')
    return value !== null && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function sameParams(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  // Whitespace and top-level key order in the escape hatch are not changes.
  const keys = Object.keys(a)
  return keys.length === Object.keys(b).length && keys.every(
    (key) => Object.hasOwn(b, key) && JSON.stringify(a[key]) === JSON.stringify(b[key])
  )
}

/** A bare id, or a header with the ids that share its prefix. */
type ModelOption =
  | { value: string }
  | {
      label: string
      options: { value: string; label: string; title: string }[]
    }

/**
 * Bucket discovered ids by their `owner/` prefix.
 *
 * That prefix is the only grouping a /models response carries in practice:
 * `_parse_ids` keeps nothing but the id, and `owned_by` — the field that looks
 * like it should be the group — is a constant on most providers. Grouping is
 * what makes a provider's few hundred ids scannable instead of a wall of
 * near-identical strings; the leaf label drops the prefix because the header
 * above it already says that, while the option's *value* stays the whole id, so
 * that is still what lands in the field when one is picked.
 *
 * Prefixless ids are emitted ungrouped and FIRST, ahead of every header: put
 * last they would sit under the final header and read as members of it. A
 * degenerate id (`/x`, `x/`) counts as prefixless too, rather than producing an
 * empty header or a blank row.
 */
function groupModelOptions(ids: string[]): ModelOption[] {
  const ungrouped: { value: string }[] = []
  // Insertion-ordered, so groups appear in the order the ids arrived — the
  // backend already returns them sorted, and re-sorting here would silently
  // give the list a different order than the flat one it replaces.
  const groups = new Map<
    string,
    { value: string; label: string; title: string }[]
  >()

  for (const id of ids) {
    const cut = id.indexOf('/')
    const owner = cut > 0 ? id.slice(0, cut) : ''
    const rest = cut > 0 ? id.slice(cut + 1) : ''
    if (!owner || !rest) {
      ungrouped.push({ value: id })
      continue
    }
    // `title` spelled out because antd would otherwise derive it from the label:
    // hovering a row should still reveal the exact id it will insert, which is
    // the one thing the shortened label no longer shows.
    const leaf = { value: id, label: rest, title: id }
    const bucket = groups.get(owner)
    if (bucket) bucket.push(leaf)
    else groups.set(owner, [leaf])
  }

  return [
    ...ungrouped,
    ...[...groups].map(([label, options]) => ({ label, options }))
  ]
}

interface Props {
  open: boolean
  /** Provider currently selected when "Add Model" was clicked. */
  defaultProvider: Provider | null
  /** Existing model to edit, or null for create mode. */
  model: Model | null
  providers: Provider[]
  onClose: () => void
  onSaved: (model: Model) => void
}

interface FormValues {
  provider_id: string
  name: string
  display_name: string
  supports_vision: 'auto' | 'on' | 'off'
  context_limit: number | null
}

export function ModelEditModal({
  open,
  defaultProvider,
  model,
  providers,
  onClose,
  onSaved
}: Props) {
  const { t, lang } = useT()
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [advancedJson, setAdvancedJson] = useState('{}')
  const [submitting, setSubmitting] = useState(false)
  const submitPending = useRef(false)
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [lookup, setLookup] = useState<{
    key: string
    data: GenerationDefaults | null
    failed: boolean
  } | null>(null)
  const initialized = useRef<string | null>(null)
  const original = useRef<Model | null>(null)
  const providerId = Form.useWatch('provider_id', form) ?? ''
  const modelName = (Form.useWatch('name', form) ?? '').trim()
  const contextLimit = Form.useWatch('context_limit', form)
  const lookupKey = JSON.stringify([providerId, modelName])
  const matchingLookup = lookup?.key === lookupKey ? lookup : null
  const defaults = matchingLookup?.data ?? (
    original.current?.provider_id === providerId && original.current?.name === modelName
      ? original.current.generation_defaults
      : null
  )
  const catalog = defaults?.catalog ?? null
  const budget = defaults?.context_budget ?? null
  const modelLimit = catalog?.context_limit ?? budget?.model_context_limit ?? null
  const lookupPending = !!providerId && !!modelName && !matchingLookup
  const advanced = useMemo(() => parseParams(advancedJson), [advancedJson])
  const advancedChanged = advanced !== null && !sameParams(advanced, original.current?.advanced_params ?? {})
  // An absent canonical key is automatic, including after deleting it in JSON.
  // The lookup describes SAVED effective settings, not this unsaved draft.
  const effort = typeof advanced?.reasoning_effort === 'string'
    ? advanced.reasoning_effort
    : 'auto'
  const effortOptions = defaults?.effort_options ?? []
  const canChooseEffort = defaults?.reasoning !== false && defaults?.reasoning_control !== 'none' && effortOptions.length > 0
  const catalogVision = catalog?.input_modalities.length
    ? catalog.input_modalities.includes('image')
    : null
  // A saved manual override is not an automatic capability result.
  const autoVision = catalogVision ?? (
    original.current?.supports_vision == null ? defaults?.effective_supports_vision : null
  )
  const formatTokens = (value: number | null | undefined) =>
    value == null ? t.modelsAdmin.unknown : value.toLocaleString(lang)

  const isEdit = !!model

  // Keyed on the fetched ids, so typing in the field (which re-renders the whole
  // Form) does not rebuild the option tree and force rc-select to re-flatten it.
  const groupedOptions = useMemo(
    () => groupModelOptions(modelOptions),
    [modelOptions]
  )

  useEffect(function initializeDraft() {
    if (!open) {
      initialized.current = null
      return
    }
    const pid = model?.provider_id ?? defaultProvider?.id ?? providers[0]?.id ?? ''
    const identity = model?.id ?? `new:${pid}`
    // Catalog refreshes must not reset edits in an already-open form.
    if (initialized.current === identity) return
    initialized.current = identity
    original.current = model
    form.resetFields()
    form.setFieldsValue({
      provider_id: pid,
      name: model?.name ?? '',
      display_name: model?.display_name ?? '',
      supports_vision: model?.supports_vision == null
        ? 'auto' : model.supports_vision ? 'on' : 'off',
      context_limit: model?.context_limit ?? null
    })
    setAdvancedJson(JSON.stringify(model?.advanced_params ?? {}, null, 2))
    setLookup(null)
  }, [open, model, defaultProvider, providers, form])

  useEffect(function lookupCapabilities() {
    if (!open || !providerId || !modelName) return
    let cancelled = false
    const timer = setTimeout(() => {
      api.getGenerationDefaults(providerId, modelName, { silent: true, fresh: true })
        .then((data) => {
          if (!cancelled) setLookup({ key: lookupKey, data, failed: false })
        })
        .catch(() => {
          if (!cancelled) setLookup({ key: lookupKey, data: null, failed: true })
        })
    }, 250)
    return function cancelLookup() {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, providerId, modelName, lookupKey])

  // Add mode only: pull available model ids from the provider's standard
  // /models endpoint for autocomplete. Failure degrades silently to empty.
  useEffect(() => {
    if (!open || model) {
      setModelOptions([])
      setLoadingModels(false)
      return
    }
    if (!providerId) {
      setModelOptions([])
      return
    }
    let cancelled = false
    setModelOptions([])
    setLoadingModels(true)
    api
      .listProviderModels(providerId, { silent: true })
      .then((ids) => {
        if (!cancelled) setModelOptions(ids)
      })
      .catch(() => {
        if (!cancelled) setModelOptions([])
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, isEdit, providerId])

  const changeEffort = (value: string) => {
    // JSON and the selector share ONE source of truth. Invalid JSON is never
    // discarded to make a selector change, and discovery never edits this draft.
    if (!advanced || !effortOptions.includes(value as ReasoningEffort)) return
    setAdvancedJson(JSON.stringify({ ...advanced, reasoning_effort: value }, null, 2))
  }

  const submit = async () => {
    if (submitPending.current) return
    submitPending.current = true
    let v: FormValues
    try {
      v = await form.validateFields()
    } catch {
      submitPending.current = false
      return
    }
    if (!advanced) {
      submitPending.current = false
      message.error(t.resources.jsonInvalid)
      return
    }
    const baseline = original.current
    const patch: Parameters<typeof api.updateModel>[1] = {}
    const vision = v.supports_vision === 'auto' ? null : v.supports_vision === 'on'
    if (v.display_name !== (baseline?.display_name ?? '')) patch.display_name = v.display_name
    if (vision !== (baseline?.supports_vision ?? null)) patch.supports_vision = vision
    if ((v.context_limit ?? null) !== (baseline?.context_limit ?? null)) {
      patch.context_limit = v.context_limit ?? null
    }
    const initialParams = baseline?.advanced_params ?? {}
    if (!sameParams(advanced, initialParams)) {
      const { reasoning_effort: selectedEffort, ...otherParams } = advanced
      const { reasoning_effort: _initialEffort, ...initialOtherParams } = initialParams
      if (
        typeof selectedEffort === 'string' &&
        effortOptions.includes(selectedEffort as ReasoningEffort) &&
        sameParams(otherParams, initialOtherParams)
      ) {
        // Canonical-only edits let the server merge the one key, preserving
        // advanced settings changed elsewhere since this dialog was opened.
        patch.reasoning_effort = selectedEffort as ReasoningEffort
      } else {
        // Explicit JSON edits (including removing the canonical key) retain the
        // full escape hatch, without a second thinking state overwriting them.
        patch.advanced_params = advanced
      }
    }
    setSubmitting(true)
    try {
      const saved = baseline
        ? Object.keys(patch).length ? await api.updateModel(baseline.id, patch) : baseline
        : await api.createModel({ provider_id: v.provider_id, name: v.name.trim(), ...patch })
      dispatchModelsChanged()
      onSaved(saved)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    } finally {
      submitPending.current = false
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={submitting ? undefined : onClose}
      title={
        isEdit ? t.modelsAdmin.editModelTitle : t.modelsAdmin.addModelTitle
      }
      okText={t.modelsAdmin.confirm}
      cancelText={t.modelsAdmin.cancel}
      onOk={submit}
      okButtonProps={{ loading: submitting }}
      cancelButtonProps={{ disabled: submitting }}
      destroyOnHidden
      width={480}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical" disabled={submitting}>
        <Form.Item
          label={t.modelsAdmin.apiProviderLabel}
          name="provider_id"
          rules={[{ required: true }]}
        >
          <Select
            disabled
            options={providers.map((p) => ({
              value: p.id,
              label: p.name,
              disabled: !p.enabled
            }))}
          />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.modelName}
          name="name"
          rules={[{ required: true, whitespace: true, max: 160 }]}
          extra={
            <div className="text-[11px]">
              <div>{t.modelsAdmin.modelNameHint}</div>
              <div role="status" title={catalog?.revision}>
                {!modelName ? t.modelsAdmin.catalogPrompt
                  : lookupPending ? t.modelsAdmin.catalogLoading
                    : matchingLookup?.failed ? t.modelsAdmin.defaultsUnavailable
                      : catalog ? t.modelsAdmin.catalogKnown
                        .replace('{source}', catalog.source)
                        .replace('{provider}', catalog.provider_id)
                        : t.modelsAdmin.catalogUnknown}
              </div>
            </div>
          }
        >
          {isEdit ? (
            <Input disabled />
          ) : (
            <AutoComplete
              options={groupedOptions}
              showSearch={{
                filterOption: (input, option) => {
                  // Group headers are offered to this filter too, ahead of their
                  // children (see rc-select's useFilterOptions). A header has no
                  // id to match on, and answering `true` would blanket-admit its
                  // whole group, so decline and let the leaves below decide —
                  // rc-select then drops any header left with no children.
                  if (!option || !('value' in option)) return false
                  // Matched against the full id, so a query still reaches a
                  // model through its prefix even though the row no longer
                  // shows one.
                  return option.value.toLowerCase().includes(input.toLowerCase())
                }
              }}
              notFoundContent={
                loadingModels ? t.modelsAdmin.modelsLoading : null
              }
            >
              {/* Custom child input so we can turn OFF the browser's native
                  autofill dropdown (saved form-history values like "123"/"test"
                  otherwise overlap our model-id suggestion list). AutoComplete
                  still owns value/onChange via Form.Item; this only customizes
                  the rendered input. */}
              <Input
                placeholder={t.modelsAdmin.modelNamePlaceholder}
                autoComplete="off"
              />
            </AutoComplete>
          )}
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.modelDisplayNameLabel}
          name="display_name"
        >
          <Input />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.thinkingLabel}
          htmlFor="model-thinking-effort"
          extra={
            <div className="text-[11px]" id="model-thinking-hint">
              <div>{thinkingHint(defaults, t)}</div>
              {defaults?.raw_override ? (
                <div className="text-msa-text-2">{t.modelsAdmin.thinkingRawOverride}</div>
              ) : null}
              {advancedChanged ? (
                <div>{t.modelsAdmin.thinkingPending}</div>
              ) : defaults && canChooseEffort && !defaults.raw_override && !lookupPending ? (
                <div>{t.modelsAdmin.thinkingEffective.replace('{value}', effortLabel(defaults.effective, t))}</div>
              ) : null}
              {advanced?.reasoning_effort !== undefined && defaults && !effortOptions.includes(effort as ReasoningEffort) ? (
                <div>{t.modelsAdmin.thinkingUnavailableOption}</div>
              ) : null}
            </div>
          }
        >
          <Select
            id="model-thinking-effort"
            aria-label={t.modelsAdmin.thinkingLabel}
            aria-describedby="model-thinking-hint"
            value={canChooseEffort ? effort : undefined}
            placeholder={defaults?.reasoning === false ? t.modelsAdmin.thinkingUnsupported
              : defaults?.reasoning === true && defaults.reasoning_control === 'none'
                ? t.modelsAdmin.thinkingFixed : t.modelsAdmin.unknown}
            labelRender={({ value }) => effortLabel(String(value), t)}
            options={effortOptions.map((value) => ({ value, label: effortLabel(value, t) }))}
            disabled={!canChooseEffort || !advanced || lookupPending || submitting}
            loading={lookupPending}
            onChange={changeEffort}
          />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.supportsVisionLabel}
          name="supports_vision"
          extra={
            <div className="text-[11px]">
              <div>{autoVision == null || lookupPending
                ? t.modelsAdmin.visionAutoPending
                : t.modelsAdmin.visionAutoResult.replace('{value}', effortLabel(autoVision ? 'on' : 'off', t))}</div>
              {catalogVision === false ? <div>{t.modelsAdmin.visionNotSupported}</div> : null}
              {catalog ? (
                <div className="mt-1">
                  {t.modelsAdmin.catalogModalities
                    .replace('{input}', catalog.input_modalities.join(', ') || t.modelsAdmin.unknown)
                    .replace('{output}', catalog.output_modalities.join(', ') || t.modelsAdmin.unknown)}
                  <div>{t.modelsAdmin.catalogModalitiesHint}</div>
                </div>
              ) : null}
            </div>
          }
        >
          <Select
            aria-label={t.modelsAdmin.supportsVisionLabel}
            options={(['auto', 'on', 'off'] as const).map((value) => ({
              value, label: effortLabel(value, t)
            }))}
          />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.contextLabel}
          name="context_limit"
          rules={[{ type: 'number', min: 1024, max: modelLimit ?? 100_000_000 }]}
          extra={
            <div className="text-[11px]">
              <div className="mt-1 flex flex-wrap gap-x-3">
                <span>{t.modelsAdmin.contextModelLimit.replace('{tokens}', formatTokens(modelLimit))}</span>
                <span>{t.modelsAdmin.contextBudget.replace('{tokens}', formatTokens(budget?.context_limit))}</span>
              </div>
              <div>{t.modelsAdmin.contextHint}</div>
              {(contextLimit ?? null) !== (original.current?.context_limit ?? null) ? (
                <div>{t.modelsAdmin.contextPending}</div>
              ) : budget ? (
                <div>{t.modelsAdmin.contextCompressionAt.replace('{tokens}', formatTokens(budget.compression_threshold))}</div>
              ) : null}
            </div>
          }
        >
          <InputNumber
            aria-label={t.modelsAdmin.contextLabel}
            className="!w-full"
            min={1024}
            max={modelLimit ?? 100_000_000}
            precision={0}
            changeOnBlur={false}
            placeholder={t.modelsAdmin.contextDefault}
          />
        </Form.Item>
        <Form.Item label={t.modelsAdmin.advancedJson}>
          <div className="overflow-hidden rounded-md border border-msa-line-1">
            <CodeEditor
              value={advancedJson}
              onChange={setAdvancedJson}
              language="json"
              height={140}
              readOnly={submitting}
            />
          </div>
          <Typography.Paragraph
            type="secondary"
            className="!mt-1 !mb-0 !text-[11px]"
          >
            {t.modelsAdmin.generationParamsHint}
            {defaults?.extra_hint ? ` · ${t.modelsAdmin.thinkingExtraHint.replace(
              '{keys}', defaults.extra_hint
            )}` : null}
          </Typography.Paragraph>
        </Form.Item>
      </Form>
    </Modal>
  )
}
