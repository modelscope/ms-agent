import { App, Form, Input, Modal, Select, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { KeyResetButton, KeyStatusTag } from '~/components/common/KeyStatus'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Protocol, Provider } from '~/lib/types'

interface Props {
  open: boolean
  /** Existing provider to edit, or null/undefined for create mode. */
  provider?: Provider | null
  onClose: () => void
  onSaved: (provider: Provider) => void
}

interface FormValues {
  id: string
  name: string
  base_url: string
  protocol: Protocol
  api_key?: string
}

export function AddProviderModal({ open, provider, onClose, onSaved }: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [advancedJson, setAdvancedJson] = useState('{}')
  const [submitting, setSubmitting] = useState(false)
  // The reset button was used: the stored key should be dropped on the next
  // Save. Purely local, like every other field in this form — so Cancel really
  // does undo it, and the tag/placeholder can preview the result meanwhile.
  const [keyCleared, setKeyCleared] = useState(false)

  const isEdit = !!provider
  // Built-in providers ship with a fixed endpoint and wire protocol; only the
  // display name and credential are the user's to change. Base URL and protocol
  // are locked (like the id), so editing one can't repoint it at a different API.
  const isBuiltin = provider?.kind === 'builtin'
  // Retain or explicitly clear both usable and unavailable stored keys.
  // The API supplies a mask and status; the mask's value is never rendered.
  const unavailable = provider?.api_key_status === 'unavailable' && !keyCleared
  const hasKey = isEdit && (!!provider?.api_key_masked || unavailable) && !keyCleared

  useEffect(() => {
    if (!open) return
    setKeyCleared(false)
    if (provider) {
      form.setFieldsValue({
        id: provider.id,
        name: provider.name,
        base_url: provider.base_url,
        protocol: provider.protocol,
        api_key: ''
      })
      setAdvancedJson(
        JSON.stringify(provider.default_generation_params ?? {}, null, 2)
      )
    } else {
      form.setFieldsValue({
        id: '',
        name: '',
        base_url: '',
        protocol: 'openai',
        api_key: ''
      })
      setAdvancedJson('{}')
    }
  }, [open, provider, form])

  // Nothing is written here: this only stages the removal and drops whatever
  // was typed, so the field and the tag agree on "no key". `submit` turns that
  // into the api_key='' the API reads as "clear it".
  const resetKey = () => {
    form.setFieldsValue({ api_key: '' })
    setKeyCleared(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    let advanced: Record<string, unknown> = {}
    try {
      const parsed = JSON.parse(advancedJson || '{}')
      if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Must be a JSON object')
      }
      advanced = parsed
    } catch (e) {
      message.error(`${t.resources.jsonInvalid} (${(e as Error).message})`)
      return
    }
    setSubmitting(true)
    try {
      let saved: Provider
      if (provider) {
        // Edit: PATCH the provider. A blank api_key keeps the existing key —
        // unless the reset staged its removal, where '' is the API's explicit
        // "clear it" signal. Omitting the field entirely can't express that.
        saved = await api.updateProvider(provider.id, {
          name: v.name,
          base_url: v.base_url,
          protocol: v.protocol,
          default_generation_params: advanced,
          ...(v.api_key
            ? { api_key: v.api_key }
            : keyCleared
              ? { api_key: '' }
              : {})
        })
      } else {
        saved = await api.createProvider({
          id: v.id,
          name: v.name,
          base_url: v.base_url,
          protocol: v.protocol,
          default_generation_params: advanced
        })
        // Custom providers are created with no API key. If the user typed one
        // in the optional field, push it as a follow-up update so it lands on
        // the mask.
        if (v.api_key) {
          saved = await api.updateProvider(saved.id, { api_key: v.api_key })
        }
      }
      onSaved(saved)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={
        isEdit
          ? t.modelsAdmin.configureProvider.replace('{name}', provider!.name)
          : t.modelsAdmin.addCustomProvider
      }
      okText={isEdit ? t.modelsAdmin.save : t.modelsAdmin.create}
      cancelText={t.modelsAdmin.cancel}
      onOk={submit}
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
      width={520}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          label={t.modelsAdmin.providerId}
          name="id"
          rules={[
            // One rule per constraint: a single rule with both `required` and
            // `pattern` would tag the pattern message onto an empty field too
            // (rule-level message, not check-level). And splitting the character
            // set from the length so the error names the ACTUAL violation — a
            // combined regex would tell users their 40-char valid id uses
            // forbidden characters when the real issue is length.
            { required: true },
            {
              pattern: /^[A-Za-z0-9][A-Za-z0-9_-]*$/,
              message: t.modelsAdmin.providerIdChars
            },
            { max: 64, message: t.modelsAdmin.providerIdTooLong }
          ]}
          extra={
            // Same treatment as the model id hint: antd's extra slot already
            // paints the description colour, only the size is overridden.
            // Worth spelling out that this is the permanent key rather than a
            // label — it explains both why it cannot be edited later and why a
            // blank display name still shows something.
            <span className="text-[11px]">{t.modelsAdmin.providerIdHint}</span>
          }
        >
          <Input placeholder="e.g. openai-compat" disabled={isEdit} />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.displayName}
          name="name"
          // Optional: the backend falls back to the id (or, for a built-in, its
          // registry display name), so an empty one still renders a sane label.
          rules={[{ max: 80 }]}
        >
          <Input placeholder={t.modelsAdmin.displayNamePlaceholder} />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.defaultBaseUrl}
          name="base_url"
          rules={[{ required: true, type: 'url' }]}
        >
          <Input
            placeholder={t.modelsAdmin.defaultBaseUrlPlaceholder}
            disabled={isBuiltin}
          />
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.protocol}
          name="protocol"
          rules={[{ required: true }]}
        >
          <Select
            disabled={isBuiltin}
            options={[
              { value: 'openai', label: t.modelsAdmin.protocolOpenAI },
              { value: 'anthropic', label: t.modelsAdmin.protocolAnthropic }
            ]}
          />
        </Form.Item>
        <Form.Item
          label={
            <span className="inline-flex items-center gap-2">
              {t.modelsAdmin.apiKey}
              {/* Whether a credential is already stored. Only meaningful when
                  editing — a provider being created has no prior state. */}
              {isEdit && (
                <KeyStatusTag set={hasKey && !unavailable}>
                  {unavailable
                    ? t.modelsAdmin.apiKeyUnavailable
                    : hasKey
                    ? t.modelsAdmin.apiKeyConfigured
                    : t.modelsAdmin.apiKeyMissing}
                </KeyStatusTag>
              )}
            </span>
          }
          name="api_key"
        >
          <Input.Password
            placeholder={
              unavailable
                ? t.modelsAdmin.apiKeyUnavailableTip
                : hasKey
                ? t.modelsAdmin.leaveBlankApiKey
                : t.modelsAdmin.apiKeyPlaceholder
            }
            suffix={
              /* Only when there is a stored key to remove. Same placement as the
                 search settings page: the reset acts on this one value, so it
                 sits in the field's suffix next to the visibility toggle. It
                 disappears once staged, since there is nothing left to clear. */
              hasKey ? (
                <KeyResetButton
                  confirmTitle={t.modelsAdmin.apiKeyResetConfirm.replace(
                    '{name}',
                    provider!.name
                  )}
                  confirmDesc={t.modelsAdmin.apiKeyResetConfirmDesc}
                  okText={t.modelsAdmin.apiKeyReset}
                  tooltip={t.modelsAdmin.apiKeyResetTip}
                  onConfirm={resetKey}
                />
              ) : null
            }
          />
        </Form.Item>
        {/* Same wording as the search settings page. The masked value the API
            returns is deliberately NOT echoed — showing which key is stored is
            not worth putting a credential fragment on screen; the tag above
            already answers "is one set?". */}
        <div className="-mt-4 mb-4 text-xs text-msa-text-3">
          {t.modelsAdmin.apiKeyNote}
        </div>
        <Form.Item label={t.modelsAdmin.advancedJson}>
          <div className="overflow-hidden rounded-md border border-msa-line-1">
            <CodeEditor
              value={advancedJson}
              onChange={setAdvancedJson}
              language="json"
              height={140}
            />
          </div>
          <Typography.Paragraph
            type="secondary"
            className="!mt-1 !mb-0 !text-[11px]"
          >
            {t.modelsAdmin.generationParamsHint}
          </Typography.Paragraph>
        </Form.Item>
      </Form>
    </Modal>
  )
}
