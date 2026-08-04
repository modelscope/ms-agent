import { App, AutoComplete, Form, Input, Modal, Select, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Model, Provider } from '~/lib/types'

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
}

export function ModelEditModal({
  open,
  defaultProvider,
  model,
  providers,
  onClose,
  onSaved
}: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [advancedJson, setAdvancedJson] = useState('{}')
  const [submitting, setSubmitting] = useState(false)
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)

  const isEdit = !!model

  useEffect(() => {
    if (!open) return
    if (model) {
      form.setFieldsValue({
        provider_id: model.provider_id,
        name: model.name,
        display_name: model.display_name
      })
      setAdvancedJson(JSON.stringify(model.advanced_params ?? {}, null, 2))
    } else {
      form.setFieldsValue({
        provider_id: defaultProvider?.id ?? providers[0]?.id ?? '',
        name: '',
        display_name: ''
      })
      setAdvancedJson('{}')
    }
  }, [open, model, defaultProvider, providers, form])

  // Add mode only: pull available model ids from the provider's standard
  // /models endpoint for autocomplete. Failure degrades silently to empty.
  useEffect(() => {
    if (!open || model) {
      setModelOptions([])
      setLoadingModels(false)
      return
    }
    const providerId = defaultProvider?.id ?? providers[0]?.id
    if (!providerId) {
      setModelOptions([])
      return
    }
    let cancelled = false
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
  }, [open, model, defaultProvider, providers])

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
      let saved: Model
      if (model) {
        saved = await api.updateModel(model.id, {
          display_name: v.display_name,
          advanced_params: advanced
        })
      } else {
        saved = await api.createModel({
          provider_id: v.provider_id,
          name: v.name,
          display_name: v.display_name,
          advanced_params: advanced
        })
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
      title={t.modelsAdmin.addModelTitle}
      okText={t.modelsAdmin.confirm}
      cancelText={t.modelsAdmin.cancel}
      onOk={submit}
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
      width={480}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          label={
            <span>
              {t.modelsAdmin.apiProviderLabel}{' '}
              <span className="text-rose-500">*</span>
            </span>
          }
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
          label={
            <span>
              {t.modelsAdmin.modelName} <span className="text-rose-500">*</span>
            </span>
          }
          name="name"
          rules={[{ required: true, max: 160 }]}
          extra={
            <span className="text-[11px] text-slate-400">
              {t.modelsAdmin.modelNameHint}
            </span>
          }
        >
          {isEdit ? (
            <Input disabled />
          ) : (
            <AutoComplete
              options={modelOptions.map((id) => ({ value: id }))}
              placeholder={t.modelsAdmin.modelNamePlaceholder}
              filterOption={(input, option) =>
                (option?.value ?? '')
                  .toString()
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
              notFoundContent={
                loadingModels ? t.modelsAdmin.modelsLoading : null
              }
            />
          )}
        </Form.Item>
        <Form.Item
          label={t.modelsAdmin.modelDisplayNameLabel}
          name="display_name"
        >
          <Input />
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
