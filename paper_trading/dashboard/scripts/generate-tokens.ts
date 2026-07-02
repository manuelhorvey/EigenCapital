import { writeFileSync, mkdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { rawTokens, tailwindOnly } from '../src/design/color-system.js'

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

// ── Step 1: Generate tokens.css ────────────────────────

let css = ':root {\n'
for (const [key, value] of Object.entries(rawTokens)) {
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
  'color-gov-green': 'gov-green.DEFAULT',
  'color-gov-green-muted': 'gov-green.muted',
  'color-gov-green-muted2': 'gov-green.muted2',
  'color-gov-yellow': 'gov-yellow.DEFAULT',
  'color-gov-yellow-muted': 'gov-yellow.muted',
  'color-gov-yellow-muted2': 'gov-yellow.muted2',
  'color-gov-red': 'gov-red.DEFAULT',
  'color-gov-red-muted': 'gov-red.muted',
  'color-gov-red-muted2': 'gov-red.muted2',
  'color-gov-init': 'gov-init.DEFAULT',
  'color-gov-init-muted': 'gov-init.muted',
  'color-gov-init-muted2': 'gov-init.muted2',
  'color-gov-gray': 'gov-gray.DEFAULT',
  'color-gov-gray-muted': 'gov-gray.muted',
  'color-gov-gray-muted2': 'gov-gray.muted2',
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
   'color-signal-warn': 'signal-warn.DEFAULT',
   'color-signal-short': 'signal-short.DEFAULT',
   'color-tripwire': 'tripwire',
   'color-accent-glow': 'accent-glow',
 }

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
