import { App, Form, Input, Modal, Select, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
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

  const isEdit = !!provider

  useEffect(() => {
    if (!open) return
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
        // Edit: PATCH the provider. Blank api_key keeps the existing key.
        saved = await api.updateProvider(provider.id, {
          name: v.name,
          base_url: v.base_url,
          protocol: v.protocol,
          default_generation_params: advanced,
          ...(v.api_key ? { api_key: v.api_key } : {})
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
      {/* messageVariables on each required item: the labels are JSX nodes (text +
          red asterisk, since requiredMark is off), which antd can't interpolate
          into its built-in validate messages — it would fall back to the raw
          field path. Feeding it the label TEXT keeps antd's own wording. */}
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          label={
            <span>
              {t.modelsAdmin.providerName}{' '}
              <span className="text-rose-500">*</span>
            </span>
          }
          name="id"
          messageVariables={{ label: t.modelsAdmin.providerName }}
          rules={[
            // Two SEPARATE rules on purpose: one rule object carrying both
            // `required` and `pattern` would report the pattern's message for an
            // empty field too, since a message belongs to the rule, not the check.
            { required: true },
            {
              pattern: /^[a-z0-9][a-z0-9_-]{0,40}$/,
              // The only custom message here: antd's built-in pattern wording
              // prints the raw regex at the user.
              message: t.modelsAdmin.providerIdHint
            }
          ]}
          extra={
            <span className="text-[11px] text-slate-400">
              {t.modelsAdmin.providerIdHint}
            </span>
          }
        >
          <Input placeholder="e.g. openai-compat" disabled={isEdit} />
        </Form.Item>
        <Form.Item
          label={
            <span>
              {t.modelsAdmin.displayName}{' '}
              <span className="text-rose-500">*</span>
            </span>
          }
          name="name"
          messageVariables={{ label: t.modelsAdmin.displayName }}
          rules={[{ required: true, max: 80 }]}
        >
          <Input placeholder={t.modelsAdmin.displayNamePlaceholder} />
        </Form.Item>
        <Form.Item label={t.modelsAdmin.defaultBaseUrl} name="base_url">
          <Input placeholder={t.modelsAdmin.defaultBaseUrlPlaceholder} />
        </Form.Item>
        <Form.Item
          label={
            <span>
              {t.modelsAdmin.protocol} <span className="text-rose-500">*</span>
            </span>
          }
          name="protocol"
          messageVariables={{ label: t.modelsAdmin.protocol }}
          rules={[{ required: true }]}
        >
          <Select
            options={[
              { value: 'openai', label: t.modelsAdmin.protocolOpenAI },
              { value: 'anthropic', label: t.modelsAdmin.protocolAnthropic }
            ]}
          />
        </Form.Item>
        <Form.Item label={t.modelsAdmin.apiKey} name="api_key">
          <Input.Password
            placeholder={
              isEdit && provider?.api_key_masked
                ? t.modelsAdmin.leaveBlankApiKey
                : t.modelsAdmin.apiKeyPlaceholder
            }
          />
        </Form.Item>
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
