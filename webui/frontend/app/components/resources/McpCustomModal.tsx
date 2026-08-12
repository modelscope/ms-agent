import { App, Form, Input, Modal, Radio, Segmented } from 'antd'
import { useEffect, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Mcp, McpTransport, Scope } from '~/lib/types'
import { fromMcpServers, toMcpServers } from './mcpJson'

interface Props {
  open: boolean
  scope: Scope
  scopeBadge?: string
  /** When provided, modal enters edit mode with pre-filled values */
  editingMcp?: Mcp | null
  onClose: () => void
  onSaved: () => void
}

const TEMPLATE = `{
  "mcpServers": {
    "stdio-server-example": {
      "command": "npx",
      "args": ["-y", "mcp-server-example"]
    },
    "sse-server-example": {
      "type": "streamable_http",
      "url": "https://example.com/mcp"
    }
  }
}
`

type TabMode = 'form' | 'json'

export function McpCustomModal({
  open,
  scope,
  scopeBadge,
  editingMcp,
  onClose,
  onSaved
}: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const isEdit = !!editingMcp
  const [tab, setTab] = useState<TabMode>('form')
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm<{
    name: string
    transport: McpTransport
    endpoint: string
    description: string
  }>()

  useEffect(() => {
    if (open) {
      setTab('form')
      if (editingMcp) {
        // Both tabs are views of the SAME server, so the JSON one is seeded with
        // the server's current config — an empty editor would look like there is
        // nothing to edit, and saving it would wipe the config.
        setText(JSON.stringify(toMcpServers([editingMcp]), null, 2))
        form.setFieldsValue({
          name: editingMcp.name,
          transport: editingMcp.transport,
          endpoint: editingMcp.endpoint,
          description: editingMcp.description
        })
      } else {
        setText('')
        form.resetFields()
      }
    }
  }, [open, form, editingMcp])

  const submitForm = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      if (isEdit) {
        await api.updateMcp(editingMcp!.id, values)
      } else {
        await api.createMcp({ ...values, enabled: true, scope })
      }
      onSaved()
    } finally {
      setSubmitting(false)
    }
  }

  const submitJson = async () => {
    let parsed
    try {
      parsed = fromMcpServers(text)
    } catch (e) {
      message.error(`${t.mcpImport.customInvalid} (${(e as Error).message})`)
      return
    }
    if (parsed.length === 0) {
      onClose()
      return
    }
    // Editing targets ONE existing server: creating from here would leave the
    // edited server untouched and silently add a duplicate beside it.
    if (isEdit && parsed.length > 1) {
      message.error(t.mcpImport.editSingleOnly)
      return
    }
    setSubmitting(true)
    try {
      if (isEdit) {
        await api.updateMcp(editingMcp!.id, parsed[0])
      } else {
        for (const m of parsed) {
          await api.createMcp({ ...m, scope })
        }
      }
      onSaved()
    } finally {
      setSubmitting(false)
    }
  }

  const transport = Form.useWatch('transport', form) ?? 'sse'

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={
        <div className="flex items-center gap-2">
          <span>
            {isEdit ? t.mcpImport.editTitle : t.mcpImport.customTitle}
          </span>
          {scopeBadge && (
            <span className="rounded bg-msa-fill-purple px-1.5 py-0.5 text-[10px] text-msa-text-brand1">
              {scopeBadge}
            </span>
          )}
        </div>
      }
      okText={isEdit ? t.resources.save : t.mcpImport.customConfirm}
      cancelText={t.resources.cancel}
      onOk={tab === 'form' ? submitForm : submitJson}
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
      width={620}
    >
      <Segmented<TabMode>
        value={tab}
        onChange={setTab}
        options={[
          // Neutral labels: these switch the VIEW (form vs raw JSON), and the
          // modal title already says whether we are adding or editing.
          { value: 'form', label: t.mcpImport.formTab },
          { value: 'json', label: t.mcpImport.jsonTab }
        ]}
        className="mb-4"
      />

      {tab === 'form' ? (
        <Form
          form={form}
          layout="vertical"
          requiredMark
          initialValues={{ transport: 'sse', description: '' }}
        >
          <Form.Item
            label={t.resources.name}
            name="name"
            rules={[{ required: true, max: 120 }]}
          >
            <Input placeholder="tavily-mcp" />
          </Form.Item>
          <Form.Item
            label={t.mcpImport.typeLabel}
            name="transport"
            rules={[{ required: true }]}
          >
            <Radio.Group>
              <Radio value="sse">SSE</Radio>
              <Radio value="http">StreamableHTTP</Radio>
              <Radio value="stdio">STDIO</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            label={
              transport === 'stdio'
                ? t.mcpImport.commandLabel
                : t.mcpImport.urlLabel
            }
            name="endpoint"
            rules={[{ required: true }]}
          >
            {transport === 'stdio' ? (
              <Input placeholder={t.mcpImport.commandPlaceholder} />
            ) : (
              <Input placeholder={t.mcpImport.urlPlaceholder} />
            )}
          </Form.Item>
          <Form.Item label={t.mcpImport.descLabel} name="description">
            <Input.TextArea
              rows={3}
              placeholder={t.mcpImport.descPlaceholder}
              classNames={{ textarea: 'resize-none' }}
            />
          </Form.Item>
        </Form>
      ) : (
        <div className="relative overflow-hidden rounded-md border border-msa-line-1">
          {/* The template hint is passed to monaco (not drawn as an overlay), so
              it lands on the same baseline/indent as the caret. */}
          <CodeEditor
            value={text}
            onChange={setText}
            language="json"
            height={360}
            placeholder={TEMPLATE}
          />
        </div>
      )}
    </Modal>
  )
}
