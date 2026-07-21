import { writeFileSync, mkdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { rawTokens, rawTokensLight, tailwindOnly } from '../src/design/color-system.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../generated')

// ── Helpers ────────────────────────────────────────────

type Obj = Record<string, unknown>

function setDeep(obj: Obj, path: string, value: unknown) {
  const parts = path.split('.')
  let cur = obj
  for (let i = 0; i < parts.length - 1; i++) {
    cur[parts[i]] ??= {}
    cur = cur[parts[i]] as Obj
  }
  cur[parts[parts.length - 1]] = value
}

const FONT_SIZES = ['hero', 'display', '2xs', 'xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl']

const camelToKebab = (s: string) => s.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()

// ── Step 1: Generate tokens.css (dark default + light overrides) ──

let css = ':root {\n'
for (const [key, value] of Object.entries(rawTokens)) {
  css += `  --${key}: ${value};\n`
}
css += '}\n\n'

// Light mode overrides — only the tokens that differ in light mode
css += '.light {\n'
for (const [key, value] of Object.entries(rawTokensLight)) {
  css += `  --${key}: ${value};\n`
}
css += '}\n\n'

for (const [name, frames] of Object.entries(tailwindOnly.keyframes)) {
  css += `@keyframes ${name} {\n`
  for (const [pct, props] of Object.entries(frames)) {
    css += `  ${pct} {\n`
    for (const [prop, val] of Object.entries(props)) {
      css += `    ${camelToKebab(prop)}: ${val};\n`
    }
    css += '  }\n'
  }
  css += '}\n\n'
}

// ── Step 2: Generate tailwind.partial.js ───────────────

// Color path map — maps rawToken key → dotted Tailwind color path
// Scale colors (teal-50, indigo-500, neutral-950) are auto-detected.
const COLOR_MAP: Record<string, string> = {
  'color-app': 'app',
  'color-surface': 'surface',
  'color-card': 'card',
  'color-panel': 'panel',
  'color-panel-hover': 'panel-hover',
  'color-text-primary': 'primary',
  'color-text-secondary': 'secondary',
  'color-text-tertiary': 'tertiary',
  'color-text-muted': 'muted',
  'color-border': 'default',
  'color-border-strong': 'strong',
  'color-glass': 'glass',
  'color-interactive-hover': 'interactive-hover',
  'color-interactive-active': 'interactive-active',
  'color-interactive-selected': 'interactive-selected',
  'color-accent-emerald': 'accent-emerald',
  'color-accent-blue': 'accent-blue',
  'color-accent-purple': 'accent-purple',
  'color-accent-amber': 'accent-amber',
  'color-accent-indigo': 'accent-indigo',
  'color-accent-pink': 'accent-pink',
   'color-chart-rose': 'chart-rose',
   'color-chart-teal': 'chart-teal',
   'color-ink': 'ink',
   'color-rule': 'rule',
   'color-signal-long': 'signal-long.DEFAULT',
   'color-signal-long-muted': 'signal-long.muted',
   'color-signal-long-muted2': 'signal-long.muted2',
   'color-signal-warn': 'signal-warn.DEFAULT',
   'color-signal-warn-muted': 'signal-warn.muted',
   'color-signal-warn-muted2': 'signal-warn.muted2',
   'color-signal-short': 'signal-short.DEFAULT',
   'color-signal-short-muted': 'signal-short.muted',
   'color-signal-short-muted2': 'signal-short.muted2',
   'color-signal-long-light': 'signal-long.light',
   'color-signal-long-dark': 'signal-long.dark',
   'color-signal-warn-light': 'signal-warn.light',
   'color-signal-warn-dark': 'signal-warn.dark',
   'color-signal-short-light': 'signal-short.light',
   'color-signal-short-dark': 'signal-short.dark',
   'color-signal-init': 'signal-init.DEFAULT',
   'color-signal-init-muted': 'signal-init.muted',
   'color-signal-init-muted2': 'signal-init.muted2',
   'color-signal-gray': 'signal-gray.DEFAULT',
   'color-signal-gray-muted': 'signal-gray.muted',
   'color-signal-gray-muted2': 'signal-gray.muted2',
   'color-tripwire': 'tripwire',
   'color-accent-glow': 'accent-glow',
 }

// Non-color tokens that are consumed directly via CSS custom properties
// (not via Tailwind color utilities). These are defined in tokens.css
// as CSS vars and accessed via var() in components.
//
// Note: table-*, input-*, badge-* tokens don't pass the `color-` prefix
// filter in the colors loop above, so they're listed here for documentation.
// They're consumed as CSS vars, not as Tailwind color utilities.

const colors: Obj = {}

for (const [key] of Object.entries(rawTokens)) {
  if (!key.startsWith('color-')) continue

  // Auto-detect scale colors: color-teal-50 → teal.50
  const scaleMatch = key.match(/^color-(teal|indigo|neutral)-(\d+)$/)
  if (scaleMatch) {
    setDeep(colors, `${scaleMatch[1]}.${scaleMatch[2]}`, `var(--${key})`)
    continue
  }

  // Check explicit map
  const mapped = COLOR_MAP[key]
  if (mapped) {
    setDeep(colors, mapped, `var(--${key})`)
  }
}

const partial = {
  colors,
  fontFamily: {
    sans: 'var(--font-sans)',
    mono: 'var(--font-mono)',
  },
  fontSize: Object.fromEntries(
    FONT_SIZES.map((s) => [
      s,
      [`var(--font-size-${s})`, { lineHeight: `var(--line-height-${s})` }],
    ]),
  ),
  lineHeight: Object.fromEntries(
    FONT_SIZES.map((s) => [s, `var(--line-height-${s})`]),
  ),
  letterSpacing: Object.fromEntries(
    Object.entries(rawTokens)
      .filter(([k]) => k.startsWith('tracking-'))
      .map(([k]) => [k.replace('tracking-', '').replace(/-/g, '-'), `var(--${k})`]),
  ),
  boxShadow: Object.fromEntries(
    Object.entries(rawTokens)
      .filter(([k]) => k.startsWith('shadow-'))
      .map(([k]) => [k.replace('shadow-', ''), `var(--${k})`]),
  ),
  spacing: Object.fromEntries(
    Object.entries(rawTokens)
      .filter(([k]) => k.startsWith('spacing-'))
      .map(([k]) => [k.replace('spacing-', '').replace(/_/g, '.'), `var(--${k})`]),
  ),
  borderRadius: Object.fromEntries(
    Object.entries(rawTokens)
      .filter(([k]) => k.startsWith('radius-'))
      .map(([k]) => [k.replace('radius-', ''), `var(--${k})`]),
  ),
  animation: Object.fromEntries(
    Object.entries(rawTokens)
      .filter(([k]) => k.startsWith('animation-'))
      .map(([k]) => [k.replace('animation-', ''), `var(--${k})`]),
  ),
  keyframes: { ...tailwindOnly.keyframes },
}

// ── Step 3: Write files ────────────────────────────────

mkdirSync(OUT, { recursive: true })

writeFileSync(resolve(OUT, 'tokens.css'), css.trimEnd() + '\n')

writeFileSync(
  resolve(OUT, 'tailwind.partial.js'),
  `// Generated by scripts/generate-tokens.ts — DO NOT EDIT MANUALLY\n` +
    `// Run \`npm run build:tokens\` to regenerate.\n` +
    `export default ${JSON.stringify(partial, null, 2)}\n`,
)

console.log('✓ generated/tokens.css')
console.log('✓ generated/tailwind.partial.js')
