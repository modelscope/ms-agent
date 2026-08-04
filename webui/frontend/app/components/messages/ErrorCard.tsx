import { ExclamationCircleFilled } from '@ant-design/icons'
import { useT } from '~/lib/i18n'

/**
 * ErrorCard — a turn/API failure as its own alert block.
 *
 * Errors are NOT part of the reply: they get an alert-framed card (danger
 * tokens, own icon + title) instead of being appended to the body text, so a
 * failure never reads as something the agent said. Used by both the live
 * stream and history replay (identical shape, no drift).
 *
 * `recoverable` distinguishes a failure the loop absorbed and kept going from
 * one that ended the turn — the hint line makes that explicit instead of
 * leaving the user guessing.
 */
export function ErrorCard({
  text,
  recoverable = false
}: {
  text: string
  /** Whether the error re-entered the model context (the turn continued). */
  recoverable?: boolean
}) {
  const { t } = useT()
  if (!text) return null
  return (
    <div
      role="alert"
      className="w-full rounded-xl border border-msa-deco-red/30 bg-msa-fill-error px-3 py-2.5"
    >
      <div className="flex items-start gap-2">
        {/* No in-house alert glyph yet — antd fallback per the icon policy. */}
        <ExclamationCircleFilled className="mt-px shrink-0 text-sm text-msa-text-danger" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-msa-text-danger">
            {recoverable ? t.chat.errorRecoverable : t.chat.errorTitle}
          </div>
          <div className="mt-1 break-words whitespace-pre-wrap text-xs leading-relaxed text-msa-text-2">
            {text}
          </div>
        </div>
      </div>
    </div>
  )
}
