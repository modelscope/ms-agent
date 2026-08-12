/**
 * MSA Design System — Single Source of Truth
 *
 * All color, radius, shadow, and typography values live here.
 * Both antd (via msaTheme.ts) and Tailwind (via CSS variable injection in root.tsx)
 * consume from this file. No duplication.
 */

/* ===== Theme-Dependent Tokens ===== */

const light = {
  bg: { 1: '#fff', 2: '#f7f9fd' },
  purple: {
    0: '#f4f2ff',
    1: '#e9e5ff',
    2: '#c8bfff',
    3: '#b2a6ff',
    4: '#9b8cff',
    5: '#624aff',
    6: '#533fd9',
    7: '#4534b2',
    8: '#36298c',
    9: '#221a59',
    10: '#181240'
  },
  blue: {
    0: '#e5f6ff',
    1: '#cceeff',
    2: '#afe0fa',
    3: '#96d8fa',
    4: '#7dcffa',
    5: '#54c1fa',
    6: '#2993cc',
    7: '#1f7099',
    8: '#144a66',
    9: '#0f374d',
    10: '#0a2533'
  },
  green: {
    0: '#e5ffff',
    1: '#ccfeff',
    2: '#b6f1f2',
    3: '#8ae4e6',
    4: '#67e4e6',
    5: '#36cfd1',
    6: '#2ba4a6',
    7: '#217e80',
    8: '#1e7273',
    9: '#175859',
    10: '#0d3333'
  },
  neutral: {
    0: '#fff',
    1: '#dbdae5',
    2: '#c4c3d9',
    3: '#9998b2',
    4: '#7c7a99',
    5: '#6b698c',
    6: '#5b5980',
    7: '#4d4b73',
    8: '#3f3d66',
    9: '#333159',
    10: '#27254c'
  },
  deco: {
    purple: '#3b29b3',
    green: '#76d9db',
    blue: '#3d75b2',
    pink: '#ffd0ff',
    yellow: '#cb8c0f',
    orange: '#ce642e',
    orange1: '#e87010',
    green2: '#329e87',
    pink2: '#c557bb',
    pink3: '#f793f7',
    red: '#d45773',
    gray: '#5b5980'
  },
  text: {
    0: '#fff',
    1: '#27254c',
    2: '#464d5b',
    3: '#8284a4',
    brand1: '#624aff',
    brand2: '#816df8',
    danger: '#d9423b',
    disabled: '#c4c3d9',
    'form-label': 'rgba(0, 0, 0, 0.85)'
  },
  icon: {
    // Neutral glyph color for icons drawn with `currentColor` (e.g. the
    // web/globe file badge). Deliberately lighter than `text-2` in dark mode:
    // an icon glyph needs more presence than body text on a dark surface.
    neutral: '#6b698c'
  },
  fill: {
    0: '#fff',
    1: '#f7f9fd',
    2: '#f3f5fa',
    3: '#eff2f9',
    4: '#f1f1fd',
    5: '#dde8f7',
    6: 'rgba(255, 255, 255, 0.7)',
    // Loading-skeleton shimmer — see the dark counterpart. Translucent black so
    // the two gradient stops actually differ (fill[2] and fill[3] are within
    // 0.02 luminance of each other, which left the shimmer motionless).
    skeleton: 'rgba(0, 0, 0, 0.06)',
    skeletonShimmer: 'rgba(0, 0, 0, 0.15)',
    trans: 'rgba(0, 0, 0, 0.7)',
    trans1: 'rgba(0, 0, 0, 0.7)',
    orangered: '#fbf1f1',
    purple: '#edefff',
    green: '#f0faf5',
    orange: '#fcf3ee',
    cyan: '#edf3f7',
    gray: '#f2f2f5',
    darkblue: 'rgba(0, 111, 220, 0.1)',
    blue: '#edeffa',
    grey: 'rgba(35, 38, 49, 0.06)',
    tag: '#f4f6fa',
    'code-box': 'rgb(255, 255, 255)',
    input: '#fff',
    error: 'rgba(212, 87, 115, 0.12)',
    warning: 'rgba(231, 174, 62, 0.12)',
    brand: '#fff'
  },
  line: {
    0: '#fff',
    1: '#ecedf1',
    2: 'rgba(231, 227, 255, 0.8)',
    3: '#6a57ff',
    input: '#d9d9d9'
  },
  gradient: {
    1: 'linear-gradient(90deg, rgba(129, 109, 248, 0.39) 0%, rgba(129, 109, 248, 0) 100%)',
    2: 'linear-gradient(91deg, rgba(65, 197, 218, 0.34) 0%, rgba(141, 226, 235, 0.27) 61%, rgba(171, 238, 242, 0.08) 86%, rgba(190, 246, 247, 0) 100%)',
    3: 'linear-gradient(93deg, rgba(203, 222, 255, 0.6) -20%, rgba(181, 207, 252, 0) 121%)'
  }
} as const

const dark = {
  bg: { 1: '#1c1c1e', 2: '#141414' },
  purple: {
    0: '#e9e5ff',
    1: '#ded9ff',
    2: '#a29bd3',
    3: '#b2a6ff',
    4: '#8573ff',
    5: '#624aff',
    6: '#533fd9',
    7: '#4534b2',
    8: '#36298c',
    9: '#191240',
    10: '#0f0b26'
  },
  blue: {
    0: '#d9f2ff',
    1: '#bfe9ff',
    2: '#afe0fa',
    3: '#96d8fa',
    4: '#71cbfa',
    5: '#49a7d9',
    6: '#2993cc',
    7: '#1f7099',
    8: '#144a66',
    9: '#0f374d',
    10: '#112733'
  },
  green: {
    0: '#d9ffff',
    1: '#bffeff',
    2: '#9df1f2',
    3: '#8ae4e6',
    4: '#5bcacc',
    5: '#2ba4a6',
    6: '#248b8c',
    7: '#217e80',
    8: '#1e7273',
    9: '#175859',
    10: '#0d3333'
  },
  neutral: {
    0: '#fff',
    1: '#e4e3ed',
    2: '#c4c3d9',
    3: '#9998b2',
    4: '#7c7a99',
    5: '#6b698c',
    6: '#5b5980',
    7: '#4d4b73',
    8: '#3f3d66',
    9: '#333159',
    10: '#27254c'
  },
  deco: {
    purple: '#968be4',
    green: '#2ba4a6',
    blue: '#5ea0c2',
    pink: '#eebeee',
    yellow: '#c1a05f',
    orange: '#ca8460',
    orange1: '#ca8460',
    green2: '#0f9c7e',
    pink2: '#ca50be',
    pink3: '#d681d6',
    red: '#bc5f74',
    gray: '#a2a1bc'
  },
  text: {
    0: '#fff',
    1: '#d8d8e3',
    2: '#9391ad',
    3: '#7a789c',
    brand1: '#816df8',
    brand2: '#c8bfff',
    danger: '#ad3b36',
    disabled: '#4e4d60',
    'form-label': 'rgba(0, 0, 0, 0.88)'
  },
  icon: {
    neutral: '#c4c3d9'
  },
  fill: {
    0: '#000',
    1: '#141414',
    2: '#202020',
    3: '#202020',
    4: '#333150',
    5: '#2d2b4d',
    6: '#0a0a0a',
    // Loading-skeleton shimmer (antd Skeleton gradient endpoints). Kept
    // TRANSLUCENT so the contrast holds on every dark surface: the opaque
    // fills above sit at #202020, which is within 1.05 contrast of the panel
    // background (#1c1c1e) — a skeleton painted in them is invisible, and with
    // fill[2] === fill[3] the shimmer had no gradient to animate either.
    skeleton: 'rgba(255, 255, 255, 0.08)',
    skeletonShimmer: 'rgba(255, 255, 255, 0.18)',
    trans: 'rgba(255, 255, 255, 0.7)',
    trans1: 'rgba(255, 255, 255, 0.7)',
    orangered: '#141414',
    purple: '#141414',
    green: '#141414',
    orange: '#141414',
    cyan: '#141414',
    gray: '#141414',
    darkblue: '#141414',
    blue: '#141414',
    grey: '#141414',
    tag: '#141414',
    'code-box': 'rgb(43, 43, 43)',
    input: '#343434',
    error: 'rgba(188, 95, 116, 0.12)',
    warning: 'rgba(193, 160, 95, 0.12)',
    brand: '#202020'
  },
  line: {
    0: '#27254c',
    1: '#28272a',
    2: '#908cac',
    3: '#6a57ff',
    input: '#626262'
  },
  gradient: {
    1: 'linear-gradient(90deg, rgba(129, 109, 248, 0.39) 0%, rgba(129, 109, 248, 0) 100%)',
    2: 'linear-gradient(91deg, rgba(65, 197, 218, 0.34) 0%, rgba(141, 226, 235, 0.27) 61%, rgba(171, 238, 242, 0.08) 86%, rgba(190, 246, 247, 0) 100%)',
    3: 'linear-gradient(90deg, rgba(70, 124, 254, 0.196) 20%, rgba(48, 139, 249, 0) 121%)'
  }
} as const

/* ===== Static Tokens (theme-independent) ===== */

const radius = {
  0: '0px',
  2: '2px',
  4: '4px',
  6: '6px',
  8: '8px',
  12: '12px',
  16: '16px',
  24: '24px',
  999: '999px',
  full: '9999px',
  'bottom-12': '0px 0px 12px 12px',
  'bottom-24': '0px 0px 24px 24px',
  'top-12': '12px 12px 0px 0px',
  'top-24': '24px 24px 0px 0px',
  'bottom-left-2': '16px 16px 16px 2px'
} as const

const shadow = {
  light: '2px 2px 10px 2px rgba(63, 63, 63, 0.04)',
  s: '0px 1px 6px 0px rgba(38, 36, 76, 0.12)',
  m: '0px 2px 32px 0px rgba(39, 37, 76, 0.08)',
  l: '0px 2px 32px 0px rgba(39, 37, 76, 0.08)',
  'effect-1': '0px 1px 6px 0px rgba(38, 36, 76, 0.12)',
  'effect-2': '0px 0px 48px 0px rgba(74, 41, 194, 0.2)',
  'effect-3':
    '0px 3px 6px -4px rgba(0, 0, 0, 0.12), 0px 6px 16px 0px rgba(0, 0, 0, 0.08), 0px 9px 28px 8px rgba(0, 0, 0, 0.05)',
  'effect-5':
    '0px 6px 16px -8px rgba(0, 0, 0, 0.08), 0px 9px 28px 0px rgba(0, 0, 0, 0.05), 0px 12px 48px 16px rgba(0, 0, 0, 0.03)',
  'button-blue-normal': '0px 6px 8px 0px rgba(97, 92, 237, 0.12)',
  'button-blue-hover': '0px 6px 8px 0px rgba(97, 92, 237, 0.2)',
  'button-red-normal': '0px 6px 8px 0px rgba(235, 47, 47, 0.12)',
  'button-red-hover': '0px 6px 8px 0px rgba(235, 47, 47, 0.2)'
} as const

const effect = {
  'blur-4': 'blur(38.08px)',
  'blur-7': 'blur(27.2px)'
} as const

const frame = {
  '1px': '1px',
  '15px': '1.5px',
  '2px': '2px'
} as const

const typography = {
  fontFamily:
    "'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', helvetica, arial, sans-serif",
  fontFamilyMono: "'Monaco', 'Menlo', 'Consolas', monospace",
  fontSize: {
    xs: '12px',
    sm: '13px',
    base: '14px',
    lg: '16px',
    xl: '18px',
    '2xl': '20px',
    '3xl': '24px',
    '4xl': '32px'
  },
  lineHeight: { tight: '1.25', base: '1.5', relaxed: '1.75' },
  fontWeight: { normal: '400', medium: '500', semibold: '600', bold: '700' }
} as const

/* ===== Exports ===== */

export const tokens = {
  light,
  dark,
  radius,
  shadow,
  effect,
  frame,
  typography
} as const

/* ===== CSS Variable Generation ===== */

type FlatEntries = Array<[string, string]>

/** Flatten a nested token object into [cssVarName, value] pairs */
function flattenThemeTokens(
  theme: Record<string, Record<string, string>>
): FlatEntries {
  const entries: FlatEntries = []
  for (const [category, values] of Object.entries(theme)) {
    for (const [key, val] of Object.entries(values as Record<string, string>)) {
      entries.push([`--msa-${category}-${key}`, val])
    }
  }
  return entries
}

function flattenStaticTokens(): FlatEntries {
  const entries: FlatEntries = []

  // Radius
  for (const [k, v] of Object.entries(radius))
    entries.push([`--msa-radius-${k}`, v])
  // Shadow
  for (const [k, v] of Object.entries(shadow))
    entries.push([`--msa-shadow-${k}`, v])
  // Effect
  for (const [k, v] of Object.entries(effect))
    entries.push([`--msa-effect-${k}`, v])
  // Frame
  for (const [k, v] of Object.entries(frame))
    entries.push([`--msa-frame-${k}`, v])
  // Typography
  entries.push(['--msa-font-family', typography.fontFamily])
  entries.push(['--msa-font-family-mono', typography.fontFamilyMono])
  for (const [k, v] of Object.entries(typography.fontSize))
    entries.push([`--msa-font-size-${k}`, v])
  for (const [k, v] of Object.entries(typography.lineHeight))
    entries.push([`--msa-line-height-${k}`, v])
  for (const [k, v] of Object.entries(typography.fontWeight))
    entries.push([`--msa-font-weight-${k}`, v])

  return entries
}

function entriesToCss(entries: FlatEntries): string {
  return entries.map(([k, v]) => `${k}:${v}`).join(';')
}

/** Pre-built CSS strings for injection in <style> */
const lightCss = entriesToCss([
  ...flattenThemeTokens(light),
  ...flattenStaticTokens()
])
const darkCss = entriesToCss(flattenThemeTokens(dark))

/**
 * Returns the full <style> innerHTML for CSS variable injection.
 * Static tokens (radius, shadow, typography) only go into :root (theme-independent).
 */
export function getDesignTokenStyleContent(): string {
  return `:root{${lightCss}}.dark{${darkCss}}`
}
