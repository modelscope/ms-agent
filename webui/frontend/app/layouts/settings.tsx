import { Tooltip } from 'antd'
import { NavLink, Outlet, useNavigate } from 'react-router'
import IconModelSettings from '~/assets/icons/model-settings.svg?react'
import IconMcpSkill from '~/assets/icons/mcp-skill-manage.svg?react'
import IconPersonalize from '~/assets/icons/personalize.svg?react'
import IconAppearance from '~/assets/icons/appearance.svg?react'

import IconBack from '~/assets/icons/back.svg?react'
import logoImg from '~/assets/images/logo.png'
import { useT } from '~/lib/i18n'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/settings'
import { getLastAppRoute } from '~/lib/lastAppRoute'
import { useMatchMedia } from '~/lib/useMatchMedia'

/** Fallback for settings routes without their own `meta` (the index route
 * redirects to Models, so it only flashes). Concrete pages override this. */
export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.title) }]
}

export default function SettingsLayout() {
  const { t } = useT()
  const navigate = useNavigate()
  // Below `md` this rail collapses to icons only (CSS-driven, see the
  // `hidden md:inline` labels), leaving nothing to say what each icon is — so
  // the label moves into a tooltip. Above `md` the label is right there and a
  // tooltip would only repeat it. Tooltips add no DOM until hovered, so keying
  // this off a media-query hook costs no layout and cannot flash.
  const compact = !useMatchMedia('(min-width: 768px)')

  const items: { to: string; label: string; icon: typeof IconModelSettings }[] =
    [
      { to: 'models', label: t.settings.navModels, icon: IconModelSettings },
      { to: 'mcp-skills', label: t.settings.navMcpSkills, icon: IconMcpSkill },
      {
        to: 'personalization',
        label: t.settings.navPersonalization,
        icon: IconPersonalize
      },
      {
        to: 'appearance',
        label: t.settings.navAppearance,
        icon: IconAppearance
      }
    ]

  const goBack = () => {
    const target = getLastAppRoute()
    if (target) navigate(target)
    else navigate('/')
  }

  return (
    <div className="flex h-screen gap-3 bg-msa-fill-1 p-3 md:gap-4 md:p-[24px]">
      {/* Left panel */}
      <aside className="flex w-[64px] shrink-0 flex-col items-center rounded-2xl md:w-60 md:items-stretch">
        {/* Brand */}
        <div className="flex items-center gap-3 px-2 py-3">
          {/* Logo sits in a white rounded tile (design spec). */}
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-msa-fill-0">
            <img
              src={logoImg}
              alt="MS-Agent"
              className="h-7 w-7 select-none"
              draggable={false}
            />
          </div>
          <span className="hidden text-sm font-semibold text-msa-text-1 md:inline">
            {t.brand}
          </span>
        </div>

        {/* Nav menu */}
        <nav className="mt-4 flex w-full flex-1 flex-col gap-1">
          {items.map((it) => (
            <Tooltip
              key={it.to}
              title={compact ? it.label : ''}
              placement="right"
            >
              <NavLink
                to={it.to}
                className={({ isActive }) =>
                  `flex items-center justify-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors md:justify-start ${
                    isActive
                      ? 'bg-msa-fill-0 font-medium text-msa-text-1'
                      : 'text-msa-text-2 hover:bg-msa-fill-3'
                  }`
                }
              >
                <it.icon className="h-5 w-5 shrink-0" />
                <span className="hidden md:inline">{it.label}</span>
              </NavLink>
            </Tooltip>
          ))}
        </nav>

        {/* Back button */}
        <Tooltip title={compact ? t.settings.back : ''} placement="right">
          <button
            onClick={goBack}
            className="flex w-full items-center justify-center gap-3 px-2 py-2 text-sm font-medium text-msa-text-1 border-none rounded-lg cursor-pointer bg-msa-fill-2 hover:bg-msa-fill-4 md:justify-start"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-msa-fill-0 shadow-sm">
              <IconBack className="h-4 w-4" />
            </span>
            <span className="hidden md:inline">{t.settings.back}</span>
          </button>
        </Tooltip>
      </aside>

      {/* Right content */}
      <main className="min-h-0 min-w-0 flex-1 overflow-auto rounded-2xl bg-msa-fill-0 py-4 px-4 md:py-[24px] md:px-[36px]">
        <Outlet />
      </main>
    </div>
  )
}
