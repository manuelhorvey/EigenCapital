// ── Design Tokens — EigenCapital Operator Console ─────────────────────────
//
// This file is the single source of truth for the dashboard's design
// tokens. It defines both dark (default) and light mode values.
//
// Architecture:
//   rawTokens        → dark-mode values (current default, written to :root)
//   rawTokensLight   → light-mode overrides (written to .light { ... })
//
// The generate-tokens.ts script reads both to produce:
//   generated/tokens.css          →  :root { --color-app: ... }
//                                   .light { --color-app: ... }
//   generated/tailwind.partial.js →  { theme: { extend: { colors: ... } }
//
// ── Naming policy ────────────────────────────────────────────────────
//
// Tokens name their *role*, not their look. Operators read 'accent',
// 'signal-long', 'rule' — they don't read 'teal-500'. This is the
// discipline that makes the system auditable: every value on every
// page must trace to a token here.
//
// ── Color strategy ──────────────────────────────────────────────────
//
// Six surface depths describe the page silhouette; three tonal
// semantics describe risk state; one accent describes brand presence.
// Eleven semantic values total. Components needing a fourth colour
// are usually computing layout (a hairline rule) — fold the value
// into the rail and stop.
//
//   ink                                background depth
//   panel / panel-hover                 section / card substrate
//   surface                            modal / scrim substrate
//   rule                               hairline separator (no shadow)
//   text-primary / -secondary / -dim / -muted
//                                       four-tone typography hierarchy
//   accent / accent-pressed / accent-glow
//                                       single brand accent (teal-emerald,
//                                       lifted from the chart palette for
//                                       hairline legibility)
//   signal-long / signal-warn / signal-short
//                                       governance semantic — used
//                                       identically across all read state
//                                       (green / yellow / red, in that
//                                       order of severity)
//   tripwire                           tripwire-ONLY signal; never
//                                       decorative. Distinct from
//                                       signal-short because tripwire
//                                       pages should *also* enter
//                                       EmergencyHaltBanner.
//
// Existing CSS-variable names below (color-app, color-text-primary,
// color-gov-green, etc.) are preserved verbatim so the Tailwind
// utility surface is unchanged for every consumer. The new token
// names below (ink / panel / rule / signal-long / etc.) are layered
// alongside for new components; migration to the role-named surface
// is a future phase.
// ──────────────────────────────────────────────────────────────────

export const rawTokens = {
  // ── Brand: Teal-Emerald (hero) ────────────────────
  'color-teal-50': '#eefdf8',
  'color-teal-100': '#d3faea',
  'color-teal-200': '#adf5d8',
  'color-teal-300': '#75ebc5',
  'color-teal-400': '#3dd9ae',
  'color-teal-500': '#14b8a6',
  'color-teal-600': '#1bb5a5',
  'color-teal-700': '#15918a',
  'color-teal-800': '#14736e',
  'color-teal-900': '#135e5a',
  'color-teal-950': '#043533',

  // ── Brand: Indigo (secondary) ─────────────────────
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

  // ── Neutral: Surface palette ──────────────────────
  'color-neutral-50': '#f3f6f5',
  'color-neutral-100': '#e1e6e4',
  'color-neutral-200': '#c3cdc8',
  'color-neutral-300': '#9eada6',
  'color-neutral-400': '#7a8d85',
  'color-neutral-500': '#5f726b',
  'color-neutral-600': '#4b5b55',
  'color-neutral-700': '#3e4a46',
  'color-neutral-800': '#2e3835',
  'color-neutral-900': '#1b221f',
  'color-neutral-950': '#0b0e0c',

  // ── Application surfaces ──────────────────────────
  // Terminal-precision: ink is one notch deeper than the previous #08090c
  // so the chrome is more clearly the chrome against the working surface.
  'color-app': '#07080b',
  'color-surface': '#0c0d12',
  'color-card': '#0c0d12',
  'color-panel': '#13161f',
  'color-panel-hover': '#161820',

  // ── Role-named tokens (canonical names) ───────────
  // These shadow the existing gov-*/border-* tokens. New components
  // should prefer these; migration of existing consumers is incremental.
  'color-ink': '#07080b',                    // same as color-app
  'color-rule': '#1e2233',                   // same as color-border
  'color-signal-long': '#25d065',            // same as color-gov-green
  'color-signal-warn': '#eab308',            // same as color-gov-yellow
  'color-signal-short': '#f04444',           // same as color-gov-red
  'color-tripwire': '#ff3864',               // distinct from signal-short — brighter, more urgent
  'color-accent-glow': 'rgba(61, 217, 174, 0.3)',

  // ── Text hierarchy ────────────────────────────────
  'color-text-primary': '#f1f3f6',
  'color-text-secondary': '#94a3b8',
  'color-text-tertiary': '#64748b',
  'color-text-muted': '#475569',

  // ── Borders ───────────────────────────────────────
  'color-border': '#1e2233',
  'color-border-strong': '#2a3040',

  // ── Glass ─────────────────────────────────────────
  'color-glass': 'rgba(12, 13, 18, 0.92)',

  // ── Focus ring ────────────────────────────────────
  'color-focus-ring': 'rgba(61, 217, 174, 0.45)',

  // ── Interactive states ────────────────────────────
  'color-interactive-hover': 'rgba(255, 255, 255, 0.04)',
  'color-interactive-active': 'rgba(255, 255, 255, 0.08)',
  'color-interactive-selected': 'rgba(61, 217, 174, 0.08)',

  // ── Governance (semantic) ─────────────────────────
  'color-gov-green': '#25d065',
  'color-gov-green-muted': 'rgba(37, 208, 101, 0.12)',
  'color-gov-green-muted2': 'rgba(37, 208, 101, 0.06)',
  'color-gov-green-light': '#16a34a',
  'color-gov-green-dark': '#15803d',

  'color-gov-yellow': '#eab308',
  'color-gov-yellow-muted': 'rgba(234, 179, 8, 0.12)',
  'color-gov-yellow-muted2': 'rgba(234, 179, 8, 0.06)',
  'color-gov-yellow-light': '#d97706',
  'color-gov-yellow-dark': '#b45309',

  'color-gov-red': '#f04444',
  'color-gov-red-muted': 'rgba(240, 68, 68, 0.12)',
  'color-gov-red-muted2': 'rgba(240, 68, 68, 0.06)',
  'color-gov-red-light': '#dc2626',
  'color-gov-red-dark': '#b91c1c',

  'color-gov-init': '#64748b',
  'color-gov-init-muted': 'rgba(100, 116, 139, 0.12)',
  'color-gov-init-muted2': 'rgba(100, 116, 139, 0.06)',

  'color-gov-gray': '#6b7280',
  'color-gov-gray-muted': 'rgba(107, 114, 128, 0.12)',
  'color-gov-gray-muted2': 'rgba(107, 114, 128, 0.06)',

  // ── Extended accent palette ───────────────────────
  // Emerald is the single accent for the operator-console identity: the
  // teal-emerald that already anchors the rail (Phase 8.1) and the
  // Header chip. Hotter (the previous #2dd4bf read as a teal at small
  // sizes; #3dd9ae reads as readable on hairline rules).
  'color-accent-emerald': '#3dd9ae',
  'color-accent-blue': '#60a5fa',
  'color-accent-purple': '#a78bfa',
  'color-accent-amber': '#fbbf24',
  'color-accent-indigo': '#818cf8',
  'color-accent-pink': '#f472b6',

  // ── Chart palette (10-color sequence) ─────────────
  'color-chart-0': '#14b8a6',
  'color-chart-1': '#60a5fa',
  'color-chart-2': '#fbbf24',
  'color-chart-3': '#f472b6',
  'color-chart-4': '#a78bfa',
  'color-chart-5': '#34d399',
  'color-chart-6': '#38bdf8',
  'color-chart-7': '#fb923c',
  'color-chart-8': '#e879f9',
  'color-chart-9': '#a3e635',

  'color-chart-rose': '#fb7185',
  'color-chart-teal': '#14b8a6',

  // ── Shadows ───────────────────────────────────────
  'shadow-panel': '0 1px 0 rgba(255,255,255,0.04) inset, 0 4px 24px rgba(0,0,0,0.35)',
  'shadow-card': '0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 32px rgba(0,0,0,0.4)',
  'shadow-modal': '0 0 0 1px rgba(255,255,255,0.04), 0 24px 80px rgba(0,0,0,0.6)',
  'shadow-tooltip': '0 4px 20px rgba(0,0,0,0.5)',
  'shadow-inner-subtle': 'inset 0 1px 3px rgba(0,0,0,0.3)',

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

  // ── Border radius ─────────────────────────────────
  'radius-DEFAULT': '6px',
  'radius-lg': '8px',
  'radius-xl': '10px',
  'radius-2xl': '12px',

  // ── Animations ────────────────────────────────────
  'animation-pulse-subtle': 'pulse-subtle 2s ease-in-out infinite',
  'animation-scale-in': 'scale-in 0.2s ease-out',
  'animation-slide-up': 'slide-up 0.35s ease-out',
  'animation-fade-in': 'fade-in 0.4s ease-out',
} as const

// ── Light Mode Overrides ──────────────────────────────────────────
// Only the tokens that differ in light mode are listed here.
// Brand scales (teal, indigo, neutral), governance colors, chart
// palette, accent colors, typography, spacing, border-radius, and
// animation tokens stay the same in both modes.
//
// The generate-tokens.ts script outputs these as a `.light { ... }`
// override block. To enable light mode, add class="light" to <html>.
export const rawTokensLight: Partial<Record<keyof typeof rawTokens, string>> = {
  // ── Application surfaces ──────────────────────────
  'color-app': '#f7f8fa',
  'color-surface': '#ffffff',
  'color-card': '#ffffff',
  'color-panel': '#eff1f5',
  'color-panel-hover': '#e5e7ed',

  // ── Role-named tokens ─────────────────────────────
  'color-ink': '#f7f8fa',                      // same as color-app
  'color-rule': '#e2e8f0',                      // lighter border
  'color-accent-glow': 'rgba(20, 184, 166, 0.15)',

  // ── Text hierarchy ────────────────────────────────
  'color-text-primary': '#0f172a',
  'color-text-secondary': '#475569',
  'color-text-tertiary': '#64748b',
  'color-text-muted': '#94a3b8',

  // ── Borders ───────────────────────────────────────
  'color-border': '#e2e8f0',
  'color-border-strong': '#cbd5e1',

  // ── Glass ─────────────────────────────────────────
  'color-glass': 'rgba(255, 255, 255, 0.92)',

  // ── Focus ring (slightly darker for light bg) ─────
  'color-focus-ring': 'rgba(20, 184, 166, 0.5)',

  // ── Interactive states ────────────────────────────
  'color-interactive-hover': 'rgba(0, 0, 0, 0.04)',
  'color-interactive-active': 'rgba(0, 0, 0, 0.08)',
  'color-interactive-selected': 'rgba(20, 184, 166, 0.1)',

  // ── Governance muted backgrounds (higher opacity for light bg) ─
  'color-gov-green-muted': 'rgba(37, 208, 101, 0.15)',
  'color-gov-green-muted2': 'rgba(37, 208, 101, 0.08)',
  'color-gov-yellow-muted': 'rgba(234, 179, 8, 0.15)',
  'color-gov-yellow-muted2': 'rgba(234, 179, 8, 0.08)',
  'color-gov-red-muted': 'rgba(240, 68, 68, 0.15)',
  'color-gov-red-muted2': 'rgba(240, 68, 68, 0.08)',
  'color-gov-init-muted': 'rgba(100, 116, 139, 0.15)',
  'color-gov-init-muted2': 'rgba(100, 116, 139, 0.08)',
  'color-gov-gray-muted': 'rgba(107, 114, 128, 0.15)',
  'color-gov-gray-muted2': 'rgba(107, 114, 128, 0.08)',

  // ── Shadows (lighter for light mode) ──────────────
  'shadow-panel': '0 1px 3px rgba(0,0,0,0.05)',
  'shadow-card': '0 4px 12px rgba(0,0,0,0.08)',
  'shadow-modal': '0 0 0 1px rgba(0,0,0,0.04), 0 24px 80px rgba(0,0,0,0.12)',
  'shadow-tooltip': '0 4px 16px rgba(0,0,0,0.1)',
  'shadow-inner-subtle': 'inset 0 1px 3px rgba(0,0,0,0.08)',
} as const

// ── Tailwind-only values (not expressible as single CSS vars) ──
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
      '0%, 100%': { opacity: '0.4', boxShadow: '0 0 0 rgba(240, 68, 68, 0)' },
      '50%': { opacity: '1', boxShadow: '0 0 8px rgba(240, 68, 68, 0.3)' },
    },
  },
} as const

// ════════════════════════════════════════════════════════════════
// Derived exports — syntactic sugar on top of rawTokens
// These stay EXACTLY as they were so no component imports break.
// ════════════════════════════════════════════════════════════════

const _ = rawTokens // shorthand

export const teal = {
  50: _['color-teal-50'],
  100: _['color-teal-100'],
  200: _['color-teal-200'],
  300: _['color-teal-300'],
  400: _['color-teal-400'],
  500: _['color-teal-500'],
  600: _['color-teal-600'],
  700: _['color-teal-700'],
  800: _['color-teal-800'],
  900: _['color-teal-900'],
  950: _['color-teal-950'],
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
  primaryAction: teal[500],
  primaryActionHover: teal[600],
  primaryActionText: neutral[950],
  secondaryAction: neutral[800],
  secondaryActionHover: neutral[700],
  activeBorder: teal[400],
  activeGlow: 'rgba(61, 217, 174, 0.3)',
  signalLong: success.DEFAULT,
  signalShort: error.DEFAULT,
  signalFlat: warning.DEFAULT,
  positive: teal[500],
  negative: error.DEFAULT,
  areaGradient: {
    from: 'rgba(45, 212, 191, 0.15)',
    to: 'rgba(45, 212, 191, 0.01)',
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
    ...tailwindOnly.fontWeight,
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
