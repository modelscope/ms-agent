import { Tooltip } from 'antd'
import { useT } from '~/lib/i18n'
import type { Provider } from '~/lib/types'
import KeyIcon from '~/assets/icons/key.svg?react'

/**
 * The at-a-glance status tags that follow a provider's name: the "built-in"
 * pill, and — after it — a key glyph when an API key is on file. Shared by the
 * provider list rail and the default-model provider dropdown so the two never
 * drift apart.
 *
 * The stored key is never sent back to the client, so its masked form is the
 * ONLY signal that one exists: an empty string means "not set". That is the
 * same fact `ProviderDetail`'s "API Key: configured" tag reports, said here as
 * a glyph so a glance down the list shows which providers are ready to use.
 */
export function ProviderTags({ provider }: { provider: Provider }) {
  const { t } = useT()
  const hasKey = !!provider.api_key_masked
  const unavailable = provider.api_key_status === 'unavailable'
  return (
    <>
      {provider.kind === 'builtin' && (
        <span className="shrink-0 rounded bg-msa-purple-6/8 px-2 py-0.5 text-xs text-msa-purple-6">
          {t.modelsAdmin.builtinBadge}
        </span>
      )}
      {hasKey && (
        <Tooltip title={t.modelsAdmin.apiKeyConfiguredTip}>
          {/* Empty native title so hovering the glyph inside a row that carries
              its own `title` (the provider list button) shows this tooltip
              alone, not the row's name tooltip stacked on top of it. */}
          <span
            title=""
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-msa-fill-green text-msa-deco-green2"
          >
            <KeyIcon className="h-4 w-4" />
          </span>
        </Tooltip>
      )}
      {unavailable && (
        <Tooltip title={t.modelsAdmin.apiKeyUnavailableTip}>
          <span className="shrink-0 rounded bg-msa-fill-2 px-2 py-0.5 text-xs text-msa-text-2">
            {t.modelsAdmin.apiKeyUnavailable}
          </span>
        </Tooltip>
      )}
    </>
  )
}
