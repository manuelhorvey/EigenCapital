import {
  teal, indigo, neutral,
  success, warning, error, neutral_semantic,
  accents, chart, background, text, border, glass, usage,
} from './color-system'

export const colors = {
  // Background hierarchy — 5 levels from deepest to surface
  app: background.app,
  surface: background.surface,
  card: background.card,
  panel: background.panel,
  'panel-hover': background['panel-hover'],

  // Text hierarchy — 4 levels
  primary: text.primary,
  secondary: text.secondary,
  tertiary: text.tertiary,
  muted: text.muted,

  // Borders
  default: border.DEFAULT,
  strong: border.strong,

  // Glass
  glass,

  // Governance (semantic)
  'gov-green': success.DEFAULT,
  'gov-yellow': warning.DEFAULT,
  'gov-red': error.DEFAULT,
  'gov-init': neutral_semantic.DEFAULT,

  // Accent palette — refined emerald as hero
  'accent-emerald': accents.emerald,
  'accent-blue': accents.blue,
  'accent-purple': accents.purple,
  'accent-amber': accents.amber,
  'accent-indigo': accents.indigo,
  'accent-pink': accents.pink,

  // Chart-specific
  'chart-rose': '#fb7185',
  'chart-teal': accents.emerald,
} as const

export const spacing = {
  0: '0px',
  px: '1px',
  0.5: '2px',
  1: '4px',
  1.5: '6px',
  2: '8px',
  2.5: '10px',
  3: '12px',
  3.5: '14px',
  4: '16px',
  5: '20px',
  6: '24px',
  7: '28px',
  8: '32px',
  9: '36px',
  10: '40px',
  11: '44px',
  12: '48px',
  14: '56px',
  16: '64px',
} as const

export const typography = {
  fontFamily: {
    sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
    mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
  },
  fontSize: {
    '2xs': ['10px', { lineHeight: '14px' }],
    xs: ['12px', { lineHeight: '16px' }],
    sm: ['14px', { lineHeight: '20px' }],
    base: ['16px', { lineHeight: '24px' }],
    lg: ['18px', { lineHeight: '24px' }],
    xl: ['20px', { lineHeight: '28px' }],
    '2xl': ['24px', { lineHeight: '32px' }],
    '3xl': ['30px', { lineHeight: '36px' }],
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
} as const

export const shadows = {
  panel: '0 1px 0 rgba(255,255,255,0.04) inset, 0 4px 24px rgba(0,0,0,0.35)',
  card: '0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 32px rgba(0,0,0,0.4)',
  modal: '0 0 0 1px rgba(255,255,255,0.04), 0 24px 80px rgba(0,0,0,0.6)',
  tooltip: '0 4px 20px rgba(0,0,0,0.5)',
} as const

export const borderRadius = {
  DEFAULT: '6px',
  lg: '8px',
  xl: '10px',
  '2xl': '12px',
} as const

export const animation = {
  pulseSubtle: 'pulse-subtle 2s ease-in-out infinite',
  scaleIn: 'scale-in 0.2s ease-out',
  slideUp: 'slide-up 0.35s ease-out',
  fadeIn: 'fade-in 0.4s ease-out',
} as const

export const tokens = {
  colors,
  spacing,
  typography,
  shadows,
  borderRadius,
  animation,
} as const
