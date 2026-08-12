import { App, Button } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Mcp, Scope } from '~/lib/types'
import { fromMcpServers, toMcpServers } from './mcpJson'

interface McpJsonViewProps {
  scope: Scope
  items: Mcp[]
  onSaved: () => void
  onCancel: () => void
}

export function McpJsonView({
  scope,
  items,
  onSaved,
  onCancel
}: McpJsonViewProps) {
  const { t } = useT()
  const { message } = App.useApp()
  const original = useMemo(
    () => JSON.stringify(toMcpServers(items), null, 2),
    [items]
  )
  const [text, setText] = useState(original)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setText(original)
  }, [original])

  const dirty = text !== original

  const save = async () => {
    let parsed
    try {
      parsed = fromMcpServers(text)
    } catch (e) {
      message.error(`${t.resources.jsonInvalid} (${(e as Error).message})`)
      return
    }
    setSaving(true)
    try {
      // ONE atomic call. Deleting every server and re-creating them from the
      // document (what this did before) meant a rename left the old server
      // behind whenever its delete was lost to a concurrent one, and a single
      // rejected entry wiped the whole scope, since the deletes had landed.
      await api.replaceMcps(
        scope,
        parsed.map((m) => ({ ...m, scope }))
      )
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-hidden rounded-xl border border-msa-line-1">
        <CodeEditor
          value={text}
          onChange={setText}
          language="json"
          height={460}
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        <Button onClick={onCancel}>{t.resources.cancel}</Button>
        <Button disabled={!dirty} onClick={() => setText(original)}>
          {t.resources.jsonReset}
        </Button>
        <Button
          type="primary"
          loading={saving}
          disabled={!dirty}
          onClick={save}
        >
          {t.resources.jsonSave}
        </Button>
      </div>
    </div>
  )
}
