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
    itemHoverColor: light.text.brand1,
    itemSelectedBg: light.bg[1],
    itemSelectedColor: light.text.brand1,
    borderRadiusSM: 6
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
    itemSelectedColor: dark.text.brand1,
    borderRadiusSM: 6
  }
}

/**
 * Build a complete antd ThemeConfig that mirrors the MSA design system.
 * Switches algorithm + map tokens based on current mode.
 */
export function getMsaAntdTheme(mode: 'light' | 'dark'): ThemeConfig {
  const isDark = mode === 'dark'
  return {
    cssVar: { prefix: 'msa-ant' },
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
    footer: 'border-t border-msa-line-1 pt-4'
  }
}
