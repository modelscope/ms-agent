import type { ReactNode } from 'react'
import { useTheme } from '~/lib/theme'
import homeBgLight from '~/assets/images/home-bg-light.png'
import homeBgDark from '~/assets/images/home-bg-dark.png'

interface Props {
  className?: string
  children: ReactNode
}

export function ChatBackdrop({ className = '', children }: Props) {
  const { theme } = useTheme()
  const src = theme === 'dark' ? homeBgDark : homeBgLight
  return (
    <div className={`relative ${className}`}>
      <div className="pointer-events-none absolute right-0 top-1/2 hidden h-full w-[360px] -translate-y-1/2 md:block">
        <img
          src={src}
          alt=""
          aria-hidden
          draggable={false}
          className="max-w-none select-none"
          style={{ width: '1471px', marginLeft: '-686px', marginTop: '-65px' }}
        />
      </div>
      <div className="z-1 relative">{children}</div>
    </div>
  )
}
