import { preserveComposerDraft } from '~/lib/composerDraft'
import { clientId } from '~/lib/clientId'
import { App, Tooltip } from 'antd'
import { BranchesOutlined } from '@ant-design/icons'
import { useRef, useState } from 'react'
import { Link, useNavigate, useRevalidator } from 'react-router'
import { api, ApiError } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { ForkOrigin } from '~/lib/types'
import { IconButton } from '../common/IconButton'

export function ForkReplyButton({ sessionId, afterSeq }: {
  sessionId: string
  afterSeq: number
}) {
  const { t } = useT()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const revalidator = useRevalidator()
  const [pending, setPending] = useState(false)
  const request = useRef<{ seq: number; id: string } | null>(null)
  const inFlight = useRef(false)
  const fork = async () => {
    if (inFlight.current) return
    if (!preserveComposerDraft(sessionId)) {
      message.info(t.chat.forkUploadPending)
      return
    }
    inFlight.current = true
    setPending(true)
    if (request.current?.seq !== afterSeq) {
      request.current = { seq: afterSeq, id: clientId() }
    }
    try {
      const child = await api.forkSession(sessionId, afterSeq, request.current.id)
      revalidator.revalidate()
      navigate(`/projects/${encodeURIComponent(child.project_id!)}/sessions/${encodeURIComponent(child.id)}`, { state: { focusComposer: true } })
    } catch (error) {
      if (!(error instanceof ApiError)) message.error(t.chat.forkFailed)
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }
  return (
    <Tooltip title={t.chat.forkReply}>
      <IconButton
        size="sm"
        aria-label={t.chat.forkReply}
        icon={<BranchesOutlined />}
        loading={pending}
        disabled={pending}
        onClick={() => void fork()}
        className="text-msa-text-3 hover:!text-msa-text-1"
      />
    </Tooltip>
  )
}

export function ForkDivider({ origin }: { origin: ForkOrigin }) {
  const { t } = useT()
  const label = t.chat.forkFrom.replace('{title}', origin.title)
  return (
    <div className="my-4 flex w-full items-center gap-3 text-xs text-msa-text-3" data-fork-origin={origin.session_id}>
      <span className="h-px min-w-4 flex-1 bg-msa-line-1" />
      {origin.available ? (
        <Link
          className="max-w-[75%] truncate text-msa-text-3 hover:text-msa-text-brand1"
          title={label}
          to={`/projects/${encodeURIComponent(origin.project_id)}/sessions/${encodeURIComponent(origin.session_id)}?at=${origin.assistant_seq}`}
        >{label}</Link>
      ) : <span className="max-w-[75%] truncate" title={`${label} · ${t.chat.forkSourceDeleted}`}>{label} · {t.chat.forkSourceDeleted}</span>}
      <span className="h-px min-w-4 flex-1 bg-msa-line-1" />
    </div>
  )
}
