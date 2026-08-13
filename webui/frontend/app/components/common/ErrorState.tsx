import type { ReactNode } from 'react'
import errorLight from '~/assets/images/error-light.png'
import errorDark from '~/assets/images/error-dark.png'
import { useTheme } from '~/lib/theme'

interface Props {
  /** Big headline — the HTTP status code, or the error's own name when a
   * client-side exception has no status. Omitted when neither exists. */
  code?: string
  /** What failed, as reported by the server. */
  description: string
  /** Primary action, usually "back home". */
  action?: ReactNode
}

/**
 * ErrorState — full-page error layout: illustration on the left, code /
 * description / action stacked on the right.
 *
 * Stacks vertically below `sm` so the illustration never squeezes the text off
 * screen on a phone. Sized against the viewport rather than the parent: `<html>`
 * carries no height, so a `h-full` chain collapses here and would pin the block
 * to the top of the page.
 */
export function ErrorState({ code, description, action }: Props) {
  const { theme } = useTheme()

  return (
    <div className="flex min-h-dvh w-full items-center justify-center overflow-auto p-8">
      <div className="flex flex-col items-center gap-6 sm:flex-row sm:gap-12">
        <img
          src={theme === 'dark' ? errorDark : errorLight}
          alt=""
          className="h-[200px] w-auto shrink-0 sm:h-[280px]"
        />
        <div className="flex flex-col items-center text-center sm:items-start sm:text-left">
          {code && (
            <div className="text-4xl font-semibold leading-tight text-msa-text-1">
              {code}
            </div>
          )}
          <p
            className={`mb-0 max-w-[420px] break-words text-sm text-msa-text-3 ${
              code ? 'mt-3' : ''
            }`}
          >
            {description}
          </p>
          {action && <div className="mt-6">{action}</div>}
        </div>
      </div>
    </div>
  )
}
