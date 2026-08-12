import { Bubble } from '@ant-design/x'
import { Tooltip } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import {
  type ComponentRef,
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState
} from 'react'
import { useT } from '~/lib/i18n'
import type { AgentMessage } from '~/lib/agentProvider'
import { AssistantMessage } from './AssistantMessage'
import { splitTurn } from './turnSplit'
import { UserBubble } from './UserBubble'
import type { OnOpenStep, OnOpenFile } from './types'
import { IconButton } from '../common/IconButton'
import DownloadIcon from '~/assets/icons/download.svg?react'
import CopyIcon from '~/assets/icons/copy.svg?react'
import './MessageList.css'

export interface ChatMessageItem {
  id: string
  message: AgentMessage
  status: string
}

/** Copy-reply action: on success the icon flips to a check for a moment
 * instead of raising a toast — feedback stays inside the bubble footer.
 * (CheckOutlined: no in-house check glyph asset yet, the established
 * fallback.) */
function CopyReplyButton({ text }: { text: string }) {
  const { t } = useT()
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    []
  )
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked (insecure context) — ignore */
    }
  }
  return (
    <Tooltip title={copied ? t.chat.copied : t.chat.copyReply}>
      <IconButton
        size="sm"
        icon={
          copied ? (
            <CheckOutlined className="text-sm !text-msa-green-5" />
          ) : (
            <CopyIcon className="h-4 w-4" />
          )
        }
        className="text-msa-text-3 hover:!text-msa-text-1"
        onClick={() => void copy()}
      />
    </Tooltip>
  )
}

/** Imperative handle so the host (ChatPanel) can jump the list to the latest
 * message — e.g. the moment the user starts typing in the composer. */
export interface MessageListHandle {
  scrollToBottom: () => void
}

interface BubbleContent {
  message: AgentMessage
  streaming: boolean
}

/**
 * Chat bubble list. Scrolling and auto-follow on new messages are delegated to
 * Bubble.List's built-in scroll container (`autoScroll`) — no external overflow
 * wrapper. The back-to-bottom button also rides on Bubble.List's own API: it
 * toggles from the built-in scroll-box position and scrolls via the list ref's
 * `scrollTo({ top: 'bottom' })`, so no hand-rolled scroll container is added.
 */
export const MessageList = forwardRef<
  MessageListHandle,
  {
    items: ChatMessageItem[]
    /** Backend session id, threaded to the plan chip (null until the first
     * turn of a brand-new chat has created the session). */
    sessionId?: string | null
    onOpenStep?: OnOpenStep
    onOpenFile?: OnOpenFile
  }
>(function MessageList({ items, sessionId, onOpenStep, onOpenFile }, ref) {
  const { t } = useT()
  const listRef = useRef<ComponentRef<typeof Bubble.List>>(null)
  const [showScrollDown, setShowScrollDown] = useState(false)

  useImperativeHandle(
    ref,
    () => ({
      scrollToBottom: () => {
        // Guard: before the list renders its scroll box (empty conversation),
        // Bubble.List's scrollTo destructures an undefined scrollBoxDom and
        // throws ("Cannot destructure property 'scrollHeight'…").
        if (!listRef.current?.scrollBoxNativeElement) return
        listRef.current.scrollTo({ top: 'bottom' })
      }
    }),
    []
  )

  // Watch Bubble.List's built-in scroll-box. It uses a column-reverse viewport,
  // so scrollTop is 0 at the visual bottom and grows negative when scrolling up
  // to read history; show the button once we move away from the bottom.
  useEffect(() => {
    const box = listRef.current?.scrollBoxNativeElement
    if (!box) return
    const onScroll = () => setShowScrollDown(Math.abs(box.scrollTop) > 120)
    onScroll()
    box.addEventListener('scroll', onScroll, { passive: true })
    return () => box.removeEventListener('scroll', onScroll)
  }, [items])

  // The newest assistant bubble in the list — its copy button stays visible;
  // all earlier replies only reveal theirs on hover.
  const latestAssistantId = [...items]
    .reverse()
    .find(({ message }) => message.role === 'assistant')?.id

  const bubbleItems = items.map(({ id, message, status }) => {
    const hasBody = !!message.content || (message.parts?.length ?? 0) > 0
    const inFlight = status === 'loading' || status === 'updating'
    const interrupted =
      message.role === 'assistant' &&
      message.parts?.some((p) => p.kind === 'interrupted')
    // Copy target: the reply's FINAL summary only (the text after the
    // "processed" fold) — mid-turn narration folded into the accordion is
    // process detail, not the answer. Parts-less messages (error/fallback)
    // copy their plain content; an interrupted turn has no summary → no button.
    const copyText =
      message.role === 'assistant' && !inFlight
        ? message.parts?.length
          ? (splitTurn(message.parts, false).summary?.text ?? '').trim()
          : (message.content || '').trim()
        : ''
    // Only the LATEST reply keeps its copy button always visible; history
    // replies reveal it on bubble hover (CSS: .msgl-copy-hover).
    const isLatestReply = id === latestAssistantId
    return {
      key: id,
      role: message.role,
      content: {
        message,
        streaming: inFlight
      } satisfies BubbleContent,
      // Show the built-in loading indicator for the in-flight assistant bubble
      // until it has actual body. `updating` (not just `loading`) is included
      // because the turn's first frame is a metadata `session` frame that flips
      // the status to `updating` while the body is still empty (backend still
      // "thinking" before the first content token).
      // Once the turn frame lands (`turnStartedAt`), AssistantMessage renders
      // its own "processing Ns" header — the dots would then be a second,
      // redundant progress hint stacked above it.
      loading: inFlight && !hasBody && message.turnStartedAt == null,
      footer:
        copyText || interrupted ? (
          <div className="flex w-full items-center justify-between">
            {/* Leftmost action: copy the reply text. */}
            {copyText ? (
              <span className={isLatestReply ? '' : 'msgl-copy-hover'}>
                <CopyReplyButton text={copyText} />
              </span>
            ) : (
              <span />
            )}
            {interrupted && (
              <span className="inline-flex items-center gap-1.5 text-xs text-msa-text-3">
                {t.chat.interrupted}
              </span>
            )}
          </div>
        ) : undefined
    }
  })

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <Bubble.List
        ref={listRef}
        autoScroll
        className="min-h-0 flex-1"
        role={{
          user: {
            placement: 'end',
            contentRender: (content: BubbleContent) => (
              <UserBubble message={content.message} onOpenFile={onOpenFile} />
            )
          },
          assistant: {
            placement: 'start',
            variant: 'borderless',
            contentRender: (content: BubbleContent) => (
              <AssistantMessage
                message={content.message}
                streaming={content.streaming}
                sessionId={sessionId}
                onOpenStep={onOpenStep}
                onOpenFile={onOpenFile}
              />
            )
          }
        }}
        items={bubbleItems}
      />
      {showScrollDown && (
        <Tooltip title={t.chat.backToBottom} placement="left">
          <IconButton
            onClick={() => {
              if (!listRef.current?.scrollBoxNativeElement) return
              listRef.current.scrollTo({ top: 'bottom', behavior: 'smooth' })
            }}
            className="absolute bottom-5 right-5 z-10 !rounded-full"
            variant="tonal"
            icon={<DownloadIcon className="h-4 w-4" />}
          ></IconButton>
        </Tooltip>
      )}
    </div>
  )
})
