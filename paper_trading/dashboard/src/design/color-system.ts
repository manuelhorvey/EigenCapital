/*
  ── QuantForge Color System ──────────────────────────
  Generated from hero accent #2dd4bf (teal-emerald)
  Hue: 170° | Saturation: 72% | Lightness: 55%

  Architecture:
    Brand  → teal-emerald (hero) + indigo (secondary)
    Neutral → warm-dark surfaces with teal undertone
    Semantic → tuned for premium data viz
    Accent  → extended palette for charts, badges, highlights
*/

/* ── Brand: Teal-Emerald (hero) ────────────────────
   Primary brand color. Used for key CTAs, active states,
   logo, and primary data series. */
export const teal = {
  50: '#eefdf8',
  100: '#d3faea',
  200: '#adf5d8',
  300: '#75ebc5',
  400: '#3dd9ae',
  500: '#2dd4bf', // hero
  600: '#1bb5a5',
  700: '#15918a',
  800: '#14736e',
  900: '#135e5a',
  950: '#043533',
} as const

/* ── Brand: Indigo (secondary) ─────────────────────
   Secondary brand. Used for secondary CTAs, selection
   states, and supporting data series. Analogous harmony
   shifted ~55° from teal for complementary depth. */
export const indigo = {
  50: '#eef2ff',
  100: '#e0e7ff',
  200: '#c9d4fe',
  300: '#a7b6fd',
  400: '#818cf8',
  500: '#6366f1',
  600: '#4f46e5',
  700: '#4338ca',
  800: '#3730a3',
  900: '#312e81',
  950: '#1e1b4b',
} as const

/* ── Neutral: Surface palette ──────────────────────
   All surfaces, text, and borders. Warm-toned with a
   subtle teal cast (H=170°) so the UI reads as cohesive.
   Used from deepest bg (950) to lightest surface (50). */
export const neutral = {
  50: '#f3f6f5',
  100: '#e1e6e4',
  200: '#c3cdc8',
  300: '#9eada6',
  400: '#7a8d85',
  500: '#5f726b',
  600: '#4b5b55',
  700: '#3e4a46',
  800: '#2e3835',
  900: '#1b221f',
  950: '#0b0e0c',
} as const

/* ── Semantic: Success / Warning / Error ────────────
   Tuned to feel premium alongside teal hero.
   Success: H=150° (analogous to teal, natural growth)
   Warning: H=45°  (warm contrast)
   Error:   H=0°   (direct tension) */
export const success = {
  DEFAULT: '#22c55e',
  muted: 'rgba(34, 197, 94, 0.12)',
  muted2: 'rgba(34, 197, 94, 0.06)',
  light: '#16a34a',
  dark: '#15803d',
}

export const warning = {
  DEFAULT: '#eab308',
  muted: 'rgba(234, 179, 8, 0.12)',
  muted2: 'rgba(234, 179, 8, 0.06)',
  light: '#d97706',
  dark: '#b45309',
}

export const error = {
  DEFAULT: '#ef4444',
  muted: 'rgba(239, 68, 68, 0.12)',
  muted2: 'rgba(239, 68, 68, 0.06)',
  light: '#dc2626',
  dark: '#b91c1c',
}

export const neutral_semantic = {
  DEFAULT: '#64748b',
  muted: 'rgba(100, 116, 139, 0.12)',
  muted2: 'rgba(100, 116, 139, 0.06)',
}

/* ── Extended Accent Palette ────────────────────────
   For charts, badges, highlights, and data viz.
   Each accent is harmonized with the teal hero. */
export const accents = {
  emerald: '#2dd4bf', // hero
  blue: '#60a5fa',
  purple: '#a78bfa',
  amber: '#fbbf24',
  indigo: '#818cf8',
  pink: '#f472b6',
} as const

/* ── Chart palette ──────────────────────────────────
   10-color sequence. First 5 are full saturation,
   last 5 are desaturated for visual hierarchy. */
export const chart = [
  '#2dd4bf', '#60a5fa', '#fbbf24', '#f472b6', '#a78bfa',
  '#5eead4', '#93c5fd', '#fde68a', '#f9a8d4', '#c4b5fd',
] as const

/* ── Background hierarchy ──────────────────────────
   5 levels from deepest canvas to hover state.
   Maps to the neutral scale for cohesive branding. */
export const background = {
  app: neutral[950],       // deep canvas
  surface: neutral[900],   // card/section surfaces
  card: neutral[900],
  panel: '#111318',        // slightly lifted (kept from original)
  'panel-hover': '#161820',
} as const

/* ── Text hierarchy ────────────────────────────────
   4 levels of text emphasis on dark backgrounds.
   Derived from neutral scale with white point tuning. */
export const text = {
  primary: neutral[50],
  secondary: neutral[300],
  tertiary: neutral[400],
  muted: neutral[500],
} as const

/* ── Border hierarchy ────────────────────────────── */
export const border = {
  DEFAULT: '#1a1d28',
  strong: '#2a3040',
} as const

/* ── Glass ───────────────────────────────────────── */
export const glass = 'rgba(12, 13, 18, 0.92)'

/* ── Usage map ─────────────────────────────────────
   Maps semantic roles to actual color tokens.
   Use this as reference when applying colors. */
export const usage = {
  // Interactive elements
  primaryAction: teal[500],
  primaryActionHover: teal[600],
  primaryActionText: neutral[950],

  secondaryAction: neutral[800],
  secondaryActionHover: neutral[700],

  // Active states
  activeBorder: teal[500],
  activeGlow: 'rgba(45, 212, 191, 0.3)',

  // Signals / direction
  signalLong: success.DEFAULT,
  signalShort: error.DEFAULT,
  signalFlat: warning.DEFAULT,

  // Gain / Loss
  positive: teal[500],
  negative: error.DEFAULT,

  // Chart colors
  areaGradient: {
    from: 'rgba(45, 212, 191, 0.15)',
    to: 'rgba(45, 212, 191, 0.01)',
  },
} as const

export const colorTokens = {
  teal,
  indigo,
  neutral,
  success,
  warning,
  error,
  neutral_semantic,
  accents,
  chart,
  background,
  text,
  border,
  glass,
  usage,
} as const
