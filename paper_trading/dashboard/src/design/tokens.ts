export const colors = {
  // Background hierarchy — 5 levels from deepest to surface
  app: '#08090c',
  surface: '#0c0d12',
  card: '#0c0d12',
  panel: '#111318',
  'panel-hover': '#161820',

  // Text hierarchy — 4 levels
  primary: '#f1f3f6',
  secondary: '#94a3b8',
  tertiary: '#64748b',
  muted: '#475569',

  // Borders
  default: '#1a1d28',
  strong: '#2a3040',

  // Glass
  glass: 'rgba(12, 13, 18, 0.92)',

  // Governance (semantic)
  'gov-green': '#22c55e',
  'gov-yellow': '#eab308',
  'gov-red': '#ef4444',
  'gov-init': '#64748b',

  // Accent palette — refined emerald as hero
  'accent-emerald': '#2dd4bf',
  'accent-blue': '#60a5fa',
  'accent-purple': '#a78bfa',
  'accent-amber': '#fbbf24',
  'accent-indigo': '#818cf8',
  'accent-pink': '#f472b6',

  // Chart-specific
  'chart-rose': '#fb7185',
  'chart-teal': '#2dd4bf',
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
