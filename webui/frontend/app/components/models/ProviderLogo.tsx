import type { FC, SVGProps } from 'react'
import type { Provider } from '~/lib/types'

/**
 * The square avatar that precedes a provider's name everywhere it is listed:
 * the settings rail, the provider detail header, the default-provider dropdown
 * and the model picker. Built-ins show their brand mark; anything without one —
 * every custom provider, and any built-in still missing a file — falls back to
 * a coloured tile bearing the name's first letter (see the screenshot spec).
 *
 * Logos are keyed by our provider id (the file's basename), discovered at build
 * time from `assets/logos/`. Dropping `assets/logos/<id>.svg` in is the whole
 * job of adding a logo — no edit here — and a custom provider can never collide
 * with a built-in mark because its id is always distinct.
 */
const modules = import.meta.glob<FC<SVGProps<SVGSVGElement>>>(
  '../../assets/logos/*.svg',
  { query: '?react', eager: true, import: 'default' }
)
const LOGOS: Record<string, FC<SVGProps<SVGSVGElement>>> = {}
for (const [path, comp] of Object.entries(modules)) {
  const id = path
    .split('/')
    .pop()!
    .replace(/\.svg$/, '')
  LOGOS[id] = comp
}

/** A stable, tasteful tile colour for lettered placeholders: the same id always
 * maps to the same hue, so a custom provider keeps its colour across the list,
 * the detail header and every selector. Lightness is held low enough that the
 * white letter stays legible on any hue. */
function placeholderColor(seed: string): string {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return `hsl(${h % 360} 52% 48%)`
}

/** First letter/digit of the name, for the placeholder tile. */
function initial(text: string): string {
  const c = [...text].find((ch) => /[A-Za-z0-9]/.test(ch))
  return (c ?? '?').toUpperCase()
}

export function ProviderLogo({
  provider,
  size = 20,
  className = ''
}: {
  provider: Pick<Provider, 'id' | 'name'>
  size?: number
  className?: string
}) {
  const Logo = LOGOS[provider.id]
  if (Logo) {
    // Bare monochrome mark, no tile behind it: a grey chip (fill-3) is within a
    // hair of the row's hover/selected fill (fill-2) in light mode, so on a
    // highlighted row the tile used to melt into the row and read as one flat
    // block. The mark stands on its own and contrasts every row background.
    return (
      <span
        style={{ width: size, height: size }}
        className={`inline-flex shrink-0 items-center justify-center text-msa-text-1 ${className}`}
      >
        <Logo
          width={Math.round(size * 0.82)}
          height={Math.round(size * 0.82)}
        />
      </span>
    )
  }
  return (
    <span
      style={{
        width: size,
        height: size,
        background: placeholderColor(provider.id || provider.name),
        fontSize: Math.round(size * 0.5)
      }}
      className={`inline-flex shrink-0 items-center justify-center rounded-md font-semibold leading-none text-white ${className}`}
    >
      {initial(provider.name || provider.id)}
    </span>
  )
}
