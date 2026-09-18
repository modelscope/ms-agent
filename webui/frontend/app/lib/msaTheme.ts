/**
 * MSA Design System → Ant Design token mapping.
 *
 * Reads all values from `designTokens.ts` (the single source of truth).
 * No hardcoded color values here — everything references the shared tokens.
 */
import { theme as antdTheme } from 'antd'
import type { ThemeConfig } from 'antd'
import { tokens } from './designTokens'
import type { XProviderProps } from '@ant-design/x'

const { light, dark, typography } = tokens

/* ===== Shared Seed Tokens (theme-independent) ===== */
const seedTokens = {
  colorPrimary: light.purple[5], // #624aff
  borderRadius: 8,
  fontFamily: typography.fontFamily,
  fontSize: 14,
  colorError: light.deco.red,
  colorWarning: light.deco.yellow,
  colorSuccess: light.green[5],
  colorInfo: light.blue[5]
}

/* ===== Light Theme Map Tokens ===== */
const lightMapTokens = {
  // Backgrounds
  colorBgContainer: light.bg[1],
  colorBgLayout: light.bg[2],
  colorBgElevated: light.fill[0],

  // Text
  colorText: light.text[1],
  colorTextSecondary: light.text[2],
  colorTextTertiary: light.text[3],
  colorTextQuaternary: light.text.disabled,

  // Fill (hover/active states)
  colorFill: light.fill[2],
  colorFillSecondary: light.fill[3],
  colorFillTertiary: light.fill[4],
  colorFillQuaternary: light.fill[1],

  // Border / Line
  colorBorder: light.line[1],

  // Link
  colorLink: light.text.brand1,
  colorLinkHover: light.text.brand2,
  colorLinkActive: light.purple[6]
}

/* ===== Dark Theme Map Tokens ===== */
const darkMapTokens = {
  // Backgrounds
  colorBgContainer: dark.bg[1],
  colorBgLayout: dark.bg[2],
  colorBgElevated: dark.fill[2],

  // Text
  colorText: dark.text[1],
  colorTextSecondary: dark.text[2],
  colorTextTertiary: dark.text[3],
  colorTextQuaternary: dark.text.disabled,

  // Fill
  colorFill: dark.fill[2],
  colorFillSecondary: dark.fill[3],
  colorFillTertiary: dark.fill[4],
  colorFillQuaternary: dark.fill[1],

  // Border / Line
  colorBorder: dark.line[1],

  // Link
  colorLink: dark.text.brand1,
  colorLinkHover: dark.text.brand2,
  colorLinkActive: dark.purple[5]
}

/* ===== Component-Level Overrides ===== */
const componentTokens = {
  Button: {
    paddingInline: 10,
    paddingInlineSM: 6
  },
  Segmented: {
    trackBg: light.fill[2],
    trackPadding: 4,
    itemColor: light.text[3],
    itemHoverColor: light.text[1],
    itemSelectedBg: light.bg[1],
    itemSelectedColor: light.text[1],
    borderRadiusSM: 6
  },
  // Flat tabs: the MSA design uses plain text colour for the active tab (the
  // purple indicator bar carries the emphasis instead of the label).
  Tabs: {
    itemSelectedColor: light.text[1],
    itemHoverColor: light.text[1],
    itemActiveColor: light.text[1]
  },
  // The workspace tree paints its own row highlight (the `highlighted` classes
  // in FolderTree.tsx), so antd's node background would double up on it.
  Tree: {
    nodeSelectedBg: 'transparent',
    nodeHoverBg: 'transparent'
  },
  // See the dark counterpart: the default gradient stops (fill[2] → fill[3]) are
  // near-identical here too, so the shimmer never appeared to move.
  Skeleton: {
    gradientFromColor: light.fill.skeleton,
    gradientToColor: light.fill.skeletonShimmer
  }
}

const darkComponentTokens = {
  Button: {
    paddingInline: 10,
    paddingInlineSM: 6
  },
  Segmented: {
    trackBg: dark.fill[2],
    trackPadding: 4,
    itemColor: dark.text[3],
    itemHoverColor: dark.text.brand1,
    itemSelectedBg: dark.bg[1],
    itemSelectedColor: dark.text[1],
    borderRadiusSM: 6
  },
  Tabs: {
    itemSelectedColor: dark.text[1],
    itemHoverColor: dark.text[1],
    itemActiveColor: dark.text[1]
  },
  Tree: {
    nodeSelectedBg: 'transparent',
    nodeHoverBg: 'transparent'
  },
  // Skeleton derives its colour from `colorFillContent`/`colorFill`, and the
  // dark map above points both at fill[2]/fill[3] — the same #202020. That made
  // loading skeletons invisible on dark panels (1.04 contrast against the
  // #1c1c1e background) with a shimmer whose two gradient stops were identical.
  // Translucent white keeps a stable contrast over any dark surface.
  Skeleton: {
    gradientFromColor: dark.fill.skeleton,
    gradientToColor: dark.fill.skeletonShimmer
  }
}

/** The modes `scripts/genAntdCss.tsx` has to bake — one CSS variable block
 * per mode ends up in the generated file. */
export const MSA_ANTD_THEME_MODES = ['light', 'dark'] as const

export type MsaThemeMode = (typeof MSA_ANTD_THEME_MODES)[number]

/**
 * Build a complete antd ThemeConfig that mirrors the MSA design system.
 * Switches algorithm + map tokens based on current mode.
 *
 * Three settings here exist only to make ZERO-RUNTIME styling work, i.e. to
 * keep the DOM in sync with the CSS baked by `scripts/genAntdCss.tsx`:
 *   - `zeroRuntime: true` — antd/x stop registering component styles at
 *     runtime (nothing is injected, on the server or in the browser), so the
 *     baked file is the ONLY source of component CSS.
 *   - `hashed: false` — otherwise every selector carries a token hash whose
 *     prefix differs between dev and production builds
 *     (`css-dev-only-do-not-override-*` vs `css-*`), and a file baked in one
 *     mode would silently miss the other.
 *   - `cssVar.key` — antd derives it from `useId()` when absent, so the class
 *     that scopes the CSS variables (`.msa-theme-light` here) would depend on
 *     the position in the render tree and never match the baked selector.
 *
 * For the same reason this must stay the app's ONLY antd theme: a nested
 * `<ConfigProvider theme={…}>` gets a `useId()`-derived css-var key, whose
 * variable block is therefore unbakeable and only appears after hydration
 * (leaving that subtree with unresolved `var(--msa-ant-*)` on first paint).
 * Per-component tweaks belong in the token maps above — even when only one
 * subtree uses the component — or in component-scoped CSS (see AGENTS.md).
 */
export function getMsaAntdTheme(mode: MsaThemeMode): ThemeConfig {
  const isDark = mode === 'dark'
  return {
    cssVar: { prefix: 'msa-ant', key: `msa-theme-${mode}` },
    hashed: false,
    zeroRuntime: true,
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      ...seedTokens,
      ...(isDark ? darkMapTokens : lightMapTokens)
    },
    components: isDark ? darkComponentTokens : componentTokens
  }
}

/* ===== Global Modal classNames ===== */
export const msaModalProps: XProviderProps['modal'] = {
  classNames: {
    header: 'border-b border-msa-line-1 pb-4 mb-4',
    footer: 'border-t border-msa-line-1 pt-4',
    container: 'max-h-[80vh] flex flex-col',
    body: 'overflow-y-auto flex-1 px-[24px] mx-[-24px]'
  }
}

/* ===== Global Drawer close placement ===== */
// Close button on the top-right, matching the app's rail headers.
export const msaDrawerProps: XProviderProps['drawer'] = {
  closable: { placement: 'end' }
}
