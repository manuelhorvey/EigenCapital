// ── Single Source of Truth ──────────────────────────
// rawTokens keys are CSS custom property names minus the `--` prefix.
// The generate-tokens script reads this map to produce:
//   generated/tokens.css          →  :root { --color-teal-50: ... }
//   generated/tailwind.partial.js →  { theme: { extend: { colors: ... } } }
// All derived exports below are syntactic sugar on top of rawTokens.
//
// DESIGN SYSTEM: "Solstice" — light-first modern fintech.
//   Light  = default (:root)  — off-white surfaces, deep emerald brand,
//            generous whitespace, soft shadows, premium SaaS clarity.
//   Dark   = `.dark` override — deep navy "Cascade" night mode with
//            emerald/cyan accents for chart-first trading focus.
// ──────────────────────────────────────────────────────────────────

export const rawTokens = {
  // ── Brand: Emerald (primary, fintech trust) ──────
  'color-emerald-50': '#ecfdf5',
  'color-emerald-100': '#d1fae5',
  'color-emerald-200': '#a7f3d0',
  'color-emerald-300': '#6ee7b7',
  'color-emerald-400': '#34d399',
  'color-emerald-500': '#10b981',
  'color-emerald-600': '#059669',
  'color-emerald-700': '#047857',
  'color-emerald-800': '#065f46',
  'color-emerald-900': '#064e3b',
  'color-emerald-950': '#022c22',

  // ── Brand: Indigo (secondary, data & depth) ──────
  'color-indigo-50': '#eef2ff',
  'color-indigo-100': '#e0e7ff',
  'color-indigo-200': '#c9d4fe',
  'color-indigo-300': '#a7b6fd',
  'color-indigo-400': '#818cf8',
  'color-indigo-500': '#6366f1',
  'color-indigo-600': '#4f46e5',
  'color-indigo-700': '#4338ca',
  'color-indigo-800': '#3730a3',
  'color-indigo-900': '#312e81',
  'color-indigo-950': '#1e1b4b',

  // ── Neutral: Slate family (warm-cool neutral scale) ──
  'color-neutral-50': '#f8fafc',
  'color-neutral-100': '#f1f5f9',
  'color-neutral-200': '#e2e8f0',
  'color-neutral-300': '#cbd5e1',
  'color-neutral-400': '#94a3b8',
  'color-neutral-500': '#64748b',
  'color-neutral-600': '#475569',
  'color-neutral-700': '#334155',
  'color-neutral-800': '#1e293b',
  'color-neutral-900': '#0f172a',
  'color-neutral-950': '#020617',

  // ── Application surfaces (light fintech base) ──────
  'color-app': '#f4f6f8',
  'color-surface': '#ffffff',
  'color-card': '#ffffff',
  'color-panel': '#ffffff',
  'color-panel-hover': '#f8fafb',

  // ── Text hierarchy ────────────────────────────────
  'color-text-primary': '#0f172a',
  'color-text-secondary': '#475569',
  'color-text-tertiary': '#64748b',
  'color-text-muted': '#94a3b8',

  // ── Borders ───────────────────────────────────────
  'color-border': '#e6e9ee',
  'color-border-strong': '#cbd5e1',

  // ── Glass ─────────────────────────────────────────
  'color-glass': 'rgba(255, 255, 255, 0.86)',

  // ── Focus ring (emerald brand) ────────────────────
  'color-focus-ring': 'rgba(4, 120, 87, 0.38)',

  // ── Interactive states ────────────────────────────
  'color-interactive-hover': 'rgba(15, 23, 42, 0.045)',
  'color-interactive-active': 'rgba(15, 23, 42, 0.08)',
  'color-interactive-selected': 'rgba(4, 120, 87, 0.09)',

  // ── Brand chrome (emerald) ────────────────────────
  'color-brand': '#047857',
  'color-brand-hover': '#065f46',
  'color-brand-soft': 'rgba(4, 120, 87, 0.10)',
  'color-brand-text': '#ffffff',

  // ── Governance (semantic) ─────────────────────────
  'color-gov-green': '#059669',
  'color-gov-green-muted': 'rgba(5, 150, 105, 0.12)',
  'color-gov-green-muted2': 'rgba(5, 150, 105, 0.06)',
  'color-gov-green-light': '#10b981',
  'color-gov-green-dark': '#047857',

  'color-gov-yellow': '#d97706',
  'color-gov-yellow-muted': 'rgba(217, 119, 6, 0.12)',
  'color-gov-yellow-muted2': 'rgba(217, 119, 6, 0.06)',
  'color-gov-yellow-light': '#f59e0b',
  'color-gov-yellow-dark': '#b45309',

  'color-gov-red': '#dc2626',
  'color-gov-red-muted': 'rgba(220, 38, 38, 0.12)',
  'color-gov-red-muted2': 'rgba(220, 38, 38, 0.06)',
  'color-gov-red-light': '#ef4444',
  'color-gov-red-dark': '#b91c1c',

  'color-gov-init': '#64748b',
  'color-gov-init-muted': 'rgba(100, 116, 139, 0.12)',
  'color-gov-init-muted2': 'rgba(100, 116, 139, 0.06)',

  'color-gov-gray': '#6b7280',
  'color-gov-gray-muted': 'rgba(107, 114, 128, 0.12)',
  'color-gov-gray-muted2': 'rgba(107, 114, 128, 0.06)',

  // ── Extended accent palette ───────────────────────
  'color-accent-emerald': '#059669',
  'color-accent-blue': '#2563eb',
  'color-accent-purple': '#7c3aed',
  'color-accent-amber': '#d97706',
  'color-accent-indigo': '#4f46e5',
  'color-accent-pink': '#db2777',

  // ── Chart palette (10-color sequence, light-safe) ──
  'color-chart-0': '#059669',
  'color-chart-1': '#2563eb',
  'color-chart-2': '#d97706',
  'color-chart-3': '#db2777',
  'color-chart-4': '#7c3aed',
  'color-chart-5': '#0d9488',
  'color-chart-6': '#0284c7',
  'color-chart-7': '#ea580c',
  'color-chart-8': '#c026d3',
  'color-chart-9': '#65a30d',

  'color-chart-rose': '#f43f5e',
  'color-chart-teal': '#0d9488',

  // ── Chart chrome (theme-aware; stronger contrast in light mode) ──
  'color-chart-grid': '#d9e0ea',
  'color-chart-axis': '#475569',
  'color-chart-tooltip-border': '#94a3b8',

  // ── Shadows (soft, light-mode appropriate) ────────
  'shadow-panel': '0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)',
  'shadow-card': '0 1px 3px rgba(15, 23, 42, 0.06), 0 8px 24px -12px rgba(15, 23, 42, 0.14)',
  'shadow-modal': '0 24px 80px -16px rgba(15, 23, 42, 0.28), 0 4px 16px rgba(15, 23, 42, 0.08)',
  'shadow-tooltip': '0 4px 20px -4px rgba(15, 23, 42, 0.16)',
  'shadow-inner-subtle': 'inset 0 1px 2px rgba(15, 23, 42, 0.04)',

  // ── Spacing (4px grid) ────────────────────────────
  'spacing-0': '0px',
  'spacing-px': '1px',
  'spacing-0_5': '2px',
  'spacing-1': '4px',
  'spacing-1_5': '6px',
  'spacing-2': '8px',
  'spacing-2_5': '10px',
  'spacing-3': '12px',
  'spacing-3_5': '14px',
  'spacing-4': '16px',
  'spacing-5': '20px',
  'spacing-6': '24px',
  'spacing-7': '28px',
  'spacing-8': '32px',
  'spacing-9': '36px',
  'spacing-10': '40px',
  'spacing-11': '44px',
  'spacing-12': '48px',
  'spacing-14': '56px',
  'spacing-16': '64px',

  // ── Typography: Font families ─────────────────────
  'font-sans': "'Inter', system-ui, sans-serif",
  'font-mono': "'JetBrains Mono', ui-monospace, monospace",

  // ── Typography: Font sizes & line heights ──────────
  'font-size-hero': '48px',
  'line-height-hero': '1.1',
  'font-size-display': '36px',
  'line-height-display': '1.15',
  'font-size-2xs': '10px',
  'line-height-2xs': '1.4',
  'font-size-xs': '12px',
  'line-height-xs': '1.3333',
  'font-size-sm': '14px',
  'line-height-sm': '1.4286',
  'font-size-base': '16px',
  'line-height-base': '1.5',
  'font-size-lg': '18px',
  'line-height-lg': '1.3333',
  'font-size-xl': '20px',
  'line-height-xl': '1.4',
  'font-size-2xl': '24px',
  'line-height-2xl': '1.3333',
  'font-size-3xl': '30px',
  'line-height-3xl': '1.2',
  'font-size-4xl': '40px',
  'line-height-4xl': '1.15',

  // ── Typography: Letter spacing ─────────────────────
  'tracking-tight': '-0.025em',
  'tracking-normal': '0em',
  'tracking-wide': '0.04em',
  'tracking-wider': '0.06em',
  'tracking-widest': '0.1em',
  'tracking-mono': '-0.02em',
  'tracking-display': '-0.03em',
  'tracking-hero': '-0.04em',

  // ── Border radius (fintech softness) ──────────────
  'radius-DEFAULT': '8px',
  'radius-lg': '10px',
  'radius-xl': '12px',
  'radius-2xl': '16px',

  // ── Animations ────────────────────────────────────
  'animation-pulse-subtle': 'pulse-subtle 2s ease-in-out infinite',
  'animation-scale-in': 'scale-in 0.2s ease-out',
  'animation-slide-up': 'slide-up 0.35s ease-out',
  'animation-fade-in': 'fade-in 0.4s ease-out',
} as const

// ── Dark-mode overrides (Cascade night theme) ──────
// Applied when `.dark` is set on <html>. Only role-mapping tokens
// that change in dark mode. Brand scales, gov colors, accents, and
// structural tokens (spacing, fonts, radii) stay the same.
export const rawDarkTokens = {
  // Surfaces — deep navy
  'color-app': '#0a0f1c',
  'color-surface': '#0d1322',
  'color-card': '#0f1626',
  'color-panel': '#121a2e',
  'color-panel-hover': '#17233c',

  // Text
  'color-text-primary': '#e2e8f0',
  'color-text-secondary': '#94a3b8',
  'color-text-tertiary': '#64748b',
  'color-text-muted': '#475569',

  // Borders
  'color-border': 'rgba(148, 163, 184, 0.16)',
  'color-border-strong': 'rgba(148, 163, 184, 0.30)',

  // Glass
  'color-glass': 'rgba(10, 15, 28, 0.86)',

  // Interactive states (dark bg → light overlays)
  'color-interactive-hover': 'rgba(255, 255, 255, 0.05)',
  'color-interactive-active': 'rgba(255, 255, 255, 0.09)',
  'color-interactive-selected': 'rgba(16, 185, 129, 0.12)',
  // Focus & selection (emerald brand)
  'color-focus-ring': 'rgba(16, 185, 129, 0.5)',

  // Brand chrome brightens on dark
  'color-brand': '#10b981',
  'color-brand-hover': '#34d399',
  'color-brand-soft': 'rgba(16, 185, 129, 0.14)',

  // Shadows (deeper on dark backgrounds)
  'shadow-panel': '0 1px 0 rgba(255,255,255,0.03) inset, 0 4px 20px rgba(0,0,0,0.35)',
  'shadow-card': '0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 32px rgba(0,0,0,0.45)',
  'shadow-modal': '0 0 0 1px rgba(255,255,255,0.04), 0 24px 80px rgba(0,0,0,0.6)',
  'shadow-tooltip': '0 4px 20px rgba(0,0,0,0.5)',
  'shadow-inner-subtle': 'inset 0 1px 3px rgba(0,0,0,0.3)',

  // Chart chrome (dark mode: subtler grid, brighter axis)
  'color-chart-grid': 'rgba(148, 163, 184, 0.14)',
  'color-chart-axis': '#94a3b8',
  'color-chart-tooltip-border': 'rgba(148, 163, 184, 0.45)',
} as const

// ════════════════════════════════════════════════════════════════
// Derived exports — syntactic sugar on top of rawTokens
// These stay EXACTLY as they were so no component imports break.
// ════════════════════════════════════════════════════════════════

const _ = rawTokens // shorthand

export const teal = {
  50: _['color-emerald-50'],
  100: _['color-emerald-100'],
  200: _['color-emerald-200'],
  300: _['color-emerald-300'],
  400: _['color-emerald-400'],
  500: _['color-emerald-500'],
  600: _['color-emerald-600'],
  700: _['color-emerald-700'],
  800: _['color-emerald-800'],
  900: _['color-emerald-900'],
  950: _['color-emerald-950'],
} as const

export const indigo = {
  50: _['color-indigo-50'],
  100: _['color-indigo-100'],
  200: _['color-indigo-200'],
  300: _['color-indigo-300'],
  400: _['color-indigo-400'],
  500: _['color-indigo-500'],
  600: _['color-indigo-600'],
  700: _['color-indigo-700'],
  800: _['color-indigo-800'],
  900: _['color-indigo-900'],
  950: _['color-indigo-950'],
} as const

export const neutral = {
  50: _['color-neutral-50'],
  100: _['color-neutral-100'],
  200: _['color-neutral-200'],
  300: _['color-neutral-300'],
  400: _['color-neutral-400'],
  500: _['color-neutral-500'],
  600: _['color-neutral-600'],
  700: _['color-neutral-700'],
  800: _['color-neutral-800'],
  900: _['color-neutral-900'],
  950: _['color-neutral-950'],
} as const

export const success = {
  DEFAULT: _['color-gov-green'],
  muted: _['color-gov-green-muted'],
  muted2: _['color-gov-green-muted2'],
  light: _['color-gov-green-light'],
  dark: _['color-gov-green-dark'],
}

export const warning = {
  DEFAULT: _['color-gov-yellow'],
  muted: _['color-gov-yellow-muted'],
  muted2: _['color-gov-yellow-muted2'],
  light: _['color-gov-yellow-light'],
  dark: _['color-gov-yellow-dark'],
}

export const error = {
  DEFAULT: _['color-gov-red'],
  muted: _['color-gov-red-muted'],
  muted2: _['color-gov-red-muted2'],
  light: _['color-gov-red-light'],
  dark: _['color-gov-red-dark'],
}

export const neutral_semantic = {
  DEFAULT: _['color-gov-init'],
  muted: _['color-gov-init-muted'],
  muted2: _['color-gov-init-muted2'],
}

export const neutral_gray = {
  DEFAULT: _['color-gov-gray'],
  muted: _['color-gov-gray-muted'],
  muted2: _['color-gov-gray-muted2'],
}

export const accents = {
  emerald: _['color-accent-emerald'],
  blue: _['color-accent-blue'],
  purple: _['color-accent-purple'],
  amber: _['color-accent-amber'],
  indigo: _['color-accent-indigo'],
  pink: _['color-accent-pink'],
} as const

export const chart = [
  _['color-chart-0'], _['color-chart-1'], _['color-chart-2'], _['color-chart-3'], _['color-chart-4'],
  _['color-chart-5'], _['color-chart-6'], _['color-chart-7'], _['color-chart-8'], _['color-chart-9'],
] as const

export const background = {
  app: _['color-app'],
  surface: _['color-surface'],
  card: _['color-card'],
  panel: _['color-panel'],
  'panel-hover': _['color-panel-hover'],
} as const

export const text = {
  primary: _['color-text-primary'],
  secondary: _['color-text-secondary'],
  tertiary: _['color-text-tertiary'],
  muted: _['color-text-muted'],
} as const

export const border = {
  DEFAULT: _['color-border'],
  strong: _['color-border-strong'],
} as const

export const glass = _['color-glass']

export const usage = {
  primaryAction: _['color-brand'],
  primaryActionHover: _['color-brand-hover'],
  primaryActionText: _['color-brand-text'],
  secondaryAction: neutral[200],
  secondaryActionHover: neutral[300],
  activeBorder: _['color-brand'],
  activeGlow: 'rgba(4, 120, 87, 0.3)',
  signalLong: success.DEFAULT,
  signalShort: error.DEFAULT,
  signalFlat: warning.DEFAULT,
  positive: teal[500],
  negative: error.DEFAULT,
  areaGradient: {
    from: 'rgba(5, 150, 105, 0.16)',
    to: 'rgba(5, 150, 105, 0.01)',
  },
} as const

export const colorTokens = {
  teal, indigo, neutral,
  success, warning, error, neutral_semantic, neutral_gray,
  accents, chart, background, text, border, glass, usage,
} as const

// ── Migrated from tokens.ts ─────────────────────────

export const spacing: Record<string, string> = {
  '0': _['spacing-0'],
  px: _['spacing-px'],
  '0.5': _['spacing-0_5'],
  '1': _['spacing-1'],
  '1.5': _['spacing-1_5'],
  '2': _['spacing-2'],
  '2.5': _['spacing-2_5'],
  '3': _['spacing-3'],
  '3.5': _['spacing-3_5'],
  '4': _['spacing-4'],
  '5': _['spacing-5'],
  '6': _['spacing-6'],
  '7': _['spacing-7'],
  '8': _['spacing-8'],
  '9': _['spacing-9'],
  '10': _['spacing-10'],
  '11': _['spacing-11'],
  '12': _['spacing-12'],
  '14': _['spacing-14'],
  '16': _['spacing-16'],
}

export const typography = {
  fontFamily: {
    sans: [_['font-sans'], 'system-ui', 'sans-serif'],
    mono: [_['font-mono'], 'ui-monospace', 'monospace'],
  },
  fontSize: {
    hero: [rawTokens['font-size-hero'], { lineHeight: rawTokens['line-height-hero'], letterSpacing: rawTokens['tracking-hero'] }],
    display: [rawTokens['font-size-display'], { lineHeight: rawTokens['line-height-display'], letterSpacing: rawTokens['tracking-display'] }],
    '2xs': [rawTokens['font-size-2xs'], { lineHeight: rawTokens['line-height-2xs'] }],
    xs: [rawTokens['font-size-xs'], { lineHeight: rawTokens['line-height-xs'] }],
    sm: [rawTokens['font-size-sm'], { lineHeight: rawTokens['line-height-sm'] }],
    base: [rawTokens['font-size-base'], { lineHeight: rawTokens['line-height-base'] }],
    lg: [rawTokens['font-size-lg'], { lineHeight: rawTokens['line-height-lg'] }],
    xl: [rawTokens['font-size-xl'], { lineHeight: rawTokens['line-height-xl'] }],
    '2xl': [rawTokens['font-size-2xl'], { lineHeight: rawTokens['line-height-2xl'] }],
    '3xl': [rawTokens['font-size-3xl'], { lineHeight: rawTokens['line-height-3xl'] }],
    '4xl': [rawTokens['font-size-4xl'], { lineHeight: rawTokens['line-height-4xl'] }],
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
    extrabold: 800,
    black: 900,
  },
  letterSpacing: {
    tight: rawTokens['tracking-tight'],
    normal: rawTokens['tracking-normal'],
    wide: rawTokens['tracking-wide'],
    wider: rawTokens['tracking-wider'],
    widest: rawTokens['tracking-widest'],
    mono: rawTokens['tracking-mono'],
    display: rawTokens['tracking-display'],
    hero: rawTokens['tracking-hero'],
  },
} as const

export const elevation = {
  low: _['shadow-panel'],
  medium: _['shadow-card'],
  high: _['shadow-modal'],
  tooltip: _['shadow-tooltip'],
} as const

export const shadows = {
  panel: _['shadow-panel'],
  card: _['shadow-card'],
  modal: _['shadow-modal'],
  tooltip: _['shadow-tooltip'],
} as const

// ── Semantic type roles ──────────────────────────────
// Maps design context → font-size token key
export const typeRoles = {
  display: '3xl',
  heading: 'xl',
  subheading: 'sm',
  body: 'xs',
  caption: '2xs',
  mono: 'xs',
} as const

// ── Gap role system ──────────────────────────────────
// Rationale for each gap value so all components use consistent spacing
export const gapRoles = {
  section: 8,
  cardCluster: 6,
  cardInternal: 4,
  metricCluster: 3,
  metricInternal: 2,
  tight: 1.5,
} as const

export const borderRadius = {
  DEFAULT: _['radius-DEFAULT'],
  lg: _['radius-lg'],
  xl: _['radius-xl'],
  '2xl': _['radius-2xl'],
} as const

export const animation = {
  pulseSubtle: _['animation-pulse-subtle'],
  scaleIn: _['animation-scale-in'],
  slideUp: _['animation-slide-up'],
  fadeIn: _['animation-fade-in'],
} as const

export const tokens = {
  colors: {
    app: _['color-app'],
    surface: _['color-surface'],
    card: _['color-card'],
    panel: _['color-panel'],
    'panel-hover': _['color-panel-hover'],
    primary: _['color-text-primary'],
    secondary: _['color-text-secondary'],
    tertiary: _['color-text-tertiary'],
    muted: _['color-text-muted'],
    default: _['color-border'],
    strong: _['color-border-strong'],
    glass: _['color-glass'],
    'interactive-hover': _['color-interactive-hover'],
    'interactive-active': _['color-interactive-active'],
    'interactive-selected': _['color-interactive-selected'],
    'gov-green': success.DEFAULT,
    'gov-yellow': warning.DEFAULT,
    'gov-red': error.DEFAULT,
    'gov-init': neutral_semantic.DEFAULT,
    'gov-gray': neutral_gray.DEFAULT,
    'accent-emerald': accents.emerald,
    'accent-blue': accents.blue,
    'accent-purple': accents.purple,
    'accent-amber': accents.amber,
    'accent-indigo': accents.indigo,
    'accent-pink': accents.pink,
    'chart-rose': _['color-chart-rose'],
    'chart-teal': _['color-chart-teal'],
  },
  spacing,
  typography,
  shadows,
  elevation,
  borderRadius,
  animation,
  typeRoles,
  gapRoles,
} as const

export const tailwindOnly = {
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  keyframes: {
    'pulse-subtle': {
      '0%, 100%': { opacity: '0.5' },
      '50%': { opacity: '1' },
    },
    'scale-in': {
      '0%': { transform: 'scale(0.97)', opacity: '0' },
      '100%': { transform: 'scale(1)', opacity: '1' },
    },
    'slide-up': {
      '0%': { transform: 'translateY(6px)', opacity: '0' },
      '100%': { transform: 'translateY(0)', opacity: '1' },
    },
    'fade-in': {
      '0%': { opacity: '0' },
      '100%': { opacity: '1' },
    },
    'state-pulse-red': {
      '0%, 100%': { opacity: '0.4', boxShadow: '0 0 0 rgba(220, 38, 38, 0)' },
      '50%': { opacity: '1', boxShadow: '0 0 8px rgba(220, 38, 38, 0.3)' },
    },
    'toast-progress': {
      '0%': { transform: 'scaleX(1)', opacity: '0.8' },
      '100%': { transform: 'scaleX(0)', opacity: '0' },
    },
  },
} as const
