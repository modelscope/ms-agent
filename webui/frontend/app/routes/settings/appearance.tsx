import { Radio } from 'antd'
import { useT } from '~/lib/i18n'
import { useTheme } from '~/lib/theme'
import appearanceLight from '~/assets/images/appearance-light.png'
import appearanceDark from '~/assets/images/appearance-dark.png'
import { metaDict, pageTitle } from '~/lib/pageTitle'
import type { Route } from './+types/appearance'

export function meta({ matches }: Route.MetaArgs) {
  const t = metaDict(matches)
  return [{ title: pageTitle(t, t.settings.navAppearance, t.settings.title) }]
}

export default function AppearanceSettings() {
  const { t, lang, setLang } = useT()
  const { theme, setTheme } = useTheme()

  return (
    <div className="space-y-8">
      {/* 外观 */}
      <section>
        <div className="mb-4 text-base font-semibold text-msa-text-1">
          {t.settings.appearanceTheme}
        </div>
        <div className="flex flex-wrap gap-4">
          <ThemeCard
            label={t.settings.themeLight}
            variant="light"
            selected={theme === 'light'}
            onClick={() => setTheme('light')}
          />
          <ThemeCard
            label={t.settings.themeDark}
            variant="dark"
            selected={theme === 'dark'}
            onClick={() => setTheme('dark')}
          />
        </div>
      </section>

      {/* 语言 */}
      <section>
        <div className="mb-4 text-base font-semibold text-msa-text-1">
          {t.settings.appearanceLanguage}
        </div>
        <Radio.Group value={lang} onChange={(e) => setLang(e.target.value)}>
          <Radio value="zh">中文</Radio>
          <Radio value="en">English</Radio>
        </Radio.Group>
      </section>
    </div>
  )
}

function ThemeCard({
  label,
  variant,
  selected,
  onClick
}: {
  label: string
  variant: 'light' | 'dark'
  selected: boolean
  onClick: () => void
}) {
  return (
    <div
      className={`w-full cursor-pointer overflow-hidden rounded-xl border-2 transition-all sm:w-[323px] ${
        selected
          ? 'border-msa-purple-5 shadow-sm'
          : 'border-msa-line-1 hover:border-msa-line-3'
      }`}
      onClick={onClick}
    >
      {/* Design-spec preview: the screenshot with the theme name overlaid
          near its bottom. Label colors are bound to the IMAGE's own palette
          (not the active theme) — dark text on the light shot, light text on
          the dark shot — so they stay readable under either app theme. */}
      <div className="relative">
        <img
          src={variant === 'light' ? appearanceLight : appearanceDark}
          alt=""
          className="block w-full select-none"
          draggable={false}
        />
        <span
          className={`absolute inset-x-0 bottom-[10px] text-center text-md font-medium ${
            variant === 'light' ? 'text-msa-text-2' : 'text-msa-text-0'
          }`}
        >
          {label}
        </span>
      </div>
    </div>
  )
}
