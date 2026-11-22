import { App, Button, Dropdown, Popconfirm, Tooltip } from 'antd'
import { useState } from 'react'
import { ApiError, api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { AgentInput, MessageSegment } from '~/lib/agentProvider'
import type { PendingInput } from '~/lib/sessionChat'
import { MsaTextArea } from '~/components/common/MsaTextArea'

export function PendingInputs({ sessionId, inputs, onSend }: {
  sessionId: string
  inputs: PendingInput[]
  onSend: (text: string, files?: AgentInput['message']['files'], segments?: MessageSegment[]) => Promise<void>
}) {
  const { t } = useT()
  const { message: toast } = App.useApp()
  const [expanded, setExpanded] = useState(false)
  const [edit, setEdit] = useState<{ item: PendingInput; content: string | MessageSegment[] } | null>(null)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const mixed = new Set(inputs.map(item => item.delivery)).size > 1
  const held = inputs.some(item => item.held)
  const allHeld = inputs.length > 0 && inputs.every(item => item.held)
  const act = async (action: () => Promise<unknown>) => {
    try { await action() } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : t.errors.requestFailed)
    }
  }
  if (!inputs.length && !edit) return null
  const textOf = (content: string | MessageSegment[]) => typeof content === 'string'
    ? content : content.map(segment => segment.type === 'text' ? segment.text : `/${segment.name ?? segment.id}`).join(' ')
  const save = async () => {
    if (!edit) return
    setSaving(true)
    try {
      await api.editInput(sessionId, edit.item.input_id, edit.item.revision,
        { ...edit.item.request, message: { ...edit.item.request.message, content: edit.content } })
      setEdit(null)
    } catch (cause) {
      setFailed(cause instanceof ApiError && cause.status === 409)
      setError(cause instanceof Error ? cause.message : t.errors.requestFailed)
    }
    finally { setSaving(false) }
  }
  return (
    <div className="mb-2 overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-2 text-sm">
      <div className="flex min-h-10 items-center justify-between gap-3 px-4 text-xs text-msa-text-3" aria-live="polite">
        <span>{allHeld ? t.followUp.paused : t.followUp.pending.replace('{count}', String(inputs.length))}</span>
        <div className="flex items-center gap-2">
          {held && <Button type="text" size="small" onClick={() => void act(() => api.resumeInputs(sessionId))}>{t.followUp.resume}</Button>}
          {inputs.length > 3 && <Button type="text" size="small" onClick={() => setExpanded(!expanded)}>
            {expanded ? t.followUp.collapse : t.followUp.expand}
          </Button>}
        </div>
      </div>
      <div className="max-h-56 overflow-y-auto overscroll-contain">
      {(expanded ? inputs : inputs.slice(0, 3)).map((item, index) => (
        <div key={item.input_id} className="flex min-h-11 items-center gap-3 border-t border-msa-line-1 px-4">
          <span className="shrink-0 text-xs tabular-nums text-msa-text-3">{index + 1}</span>
          <details className="min-w-0 flex-1 py-2">
            <summary className="cursor-pointer list-none truncate text-msa-text-2">{textOf(item.request.message.content)}</summary>
            <p className="mt-2 whitespace-pre-wrap break-words leading-relaxed text-msa-text-2">{textOf(item.request.message.content)}</p>
            {!!item.request.message.files?.length && <p className="mt-1 text-xs text-msa-text-3">{item.request.message.files.map(file => file.name).join(' · ')}</p>}
            {item.error && <p role="alert" className="mt-1 text-xs text-msa-text-3">{item.error}</p>}
          </details>
          {item.held && !allHeld && <span className="shrink-0 text-xs text-msa-text-3">{t.followUp.paused}</span>}
          {mixed && <span className="shrink-0 text-xs text-msa-text-3">{item.delivery === 'steer' ? t.followUp.thisTurn : t.followUp.nextTurn}</span>}
          {!!item.request.message.files?.length && <span className="text-xs text-msa-text-3">{t.followUp.attachments.replace('{count}', String(item.request.message.files.length))}</span>}
          <Dropdown trigger={['click']} menu={{ items: [
            { key: 'edit', label: t.followUp.edit, onClick: () => { setEdit({ item, content: item.request.message.content }); setFailed(false); setError('') } },
            { key: 'withdraw', label: <Popconfirm title={t.followUp.withdrawConfirm}
              okText={t.followUp.withdraw} cancelText={t.followUp.cancel}
              onConfirm={() => act(() => api.withdrawInput(sessionId, item.input_id, item.revision))}>
              <span onClick={event => event.stopPropagation()}>{t.followUp.withdraw}</span>
            </Popconfirm> }
          ] }}>
            <Tooltip title={t.followUp.more}><Button type="text" className="min-h-11 min-w-11" aria-label={t.followUp.more}>···</Button></Tooltip>
          </Dropdown>
        </div>
      ))}
      </div>
      {edit && <div className="max-h-60 space-y-2 overflow-y-auto border-t border-msa-line-1 p-3">
        {typeof edit.content === 'string'
          ? <MsaTextArea aria-label={t.followUp.edit} value={edit.content} autoSize={{ minRows: 2, maxRows: 6 }}
            onChange={event => setEdit({ ...edit, content: event.target.value })} />
          : edit.content.map((segment, index) => segment.type === 'skill'
            ? <span key={index} className="inline-block rounded-md bg-msa-fill-3 px-2 py-1 text-xs">/{segment.name ?? segment.id}</span>
            : <MsaTextArea key={index} aria-label={t.followUp.edit} value={segment.text} autoSize={{ minRows: 1, maxRows: 4 }}
              onChange={event => setEdit({ ...edit, content: (edit.content as MessageSegment[]).map((s, i) => i === index ? { type: 'text', text: event.target.value } : s) })} />)}
        {error && <p role="alert" className="text-xs text-msa-text-3">{failed ? t.followUp.editConflict : error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="text" onClick={() => setEdit(null)}>{t.followUp.cancel}</Button>
          {failed && <Button onClick={() => void act(async () => {
            await onSend(textOf(edit.content), edit.item.request.message.files,
              Array.isArray(edit.content) ? edit.content : undefined)
            setEdit(null)
          })}>{t.home.send}</Button>}
          <Button type="primary" loading={saving} onClick={() => void save()}>{t.followUp.save}</Button>
        </div>
      </div>}
    </div>
  )
}
