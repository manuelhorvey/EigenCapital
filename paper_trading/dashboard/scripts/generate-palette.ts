#!/usr/bin/env tsx
/**
 * generate-palette.ts — Quorrin Color Palette Generator
 *
 * Usage:
 *   tsx scripts/generate-palette.ts <seed-color> [--mode dark|light] [--output json|css|tailwind]
 *
 * Examples:
 *   tsx scripts/generate-palette.ts '#14b8a6' --output css
 *   tsx scripts/generate-palette.ts '#6366f1' --mode light --output tailwind
 *   tsx scripts/generate-palette.ts '#60a5fa' --output json
 *
 * Generates a full brand palette from a single seed hex color:
 *   - 11-step scale (50–950) via lightness interpolation
 *   - Semantic color mapping (success, warning, error, info)
 *   - Chart palette (10-color harmonious sequence)
 *   - Surface/background, text, border tokens for both dark and light modes
 *
 * No external dependencies — uses pure HSL math.
 */

import { writeFileSync, mkdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// ── Types ───────────────────────────────────────────────

interface HSL {
  h: number // 0–360
  s: number // 0–100
  l: number // 0–100
}

interface Palette {
  seed: string
  scale: Record<string, string>   // 50–950
  brand: Record<string, string>   // named accents
  chart: string[]                 // 10-color sequence
  semantic: {
    success: string
    warning: string
    error: string
    info: string
  }
  surfaces: {                     // dark + light surface tokens
    dark: SurfaceTokens
    light: SurfaceTokens
  }
}

interface SurfaceTokens {
  app: string
  surface: string
  card: string
  panel: string
  'panel-hover': string
  'text-primary': string
  'text-secondary': string
  'text-tertiary': string
  'text-muted': string
  border: string
  'border-strong': string
  glass: string
}

// ── Color Math ──────────────────────────────────────────

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function rgbToHsl(r: number, g: number, b: number): HSL {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b)
  let h = 0, s = 0
  const l = (max + min) / 2

  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break
      case g: h = ((b - r) / d + 2) / 6; break
      case b: h = ((r - g) / d + 4) / 6; break
    }
  }

  return { h: h * 360, s: s * 100, l: l * 100 }
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h /= 360; s /= 100; l /= 100
  let r: number, g: number, b: number

  if (s === 0) {
    r = g = b = l
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1
      if (t > 1) t -= 1
      if (t < 1/6) return p + (q - p) * 6 * t
      if (t < 1/2) return q
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6
      return p
    }
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s
    const p = 2 * l - q
    r = hue2rgb(p, q, h + 1/3)
    g = hue2rgb(p, q, h)
    b = hue2rgb(p, q, h - 1/3)
  }

  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)]
}

function hslToHex(h: number, s: number, l: number): string {
  const [r, g, b] = hslToRgb(h, s, l)
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

function hexToHsl(hex: string): HSL {
  const [r, g, b] = hexToRgb(hex)
  return rgbToHsl(r, g, b)
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val))
}

// ── Palette Generation ─────────────────────────────────

// Scale stops and their target lightness values (0–100)
// Inspired by Tailwind's scale distribution
const SCALE_STOPS: [string, number][] = [
  ['50', 97],
  ['100', 93],
  ['200', 86],
  ['300', 74],
  ['400', 60],
  ['500', 47],  // anchor — closest to seed
  ['600', 39],
  ['700', 32],
  ['800', 26],
  ['900', 19],
  ['950', 12],
]

function generateScale(seedHSL: HSL): Record<string, string> {
  const scale: Record<string, string> = {}

  // Find the anchor stop closest to seed lightness
  const seedL = seedHSL.l
  let anchorStop = 500
  let minDiff = Infinity
  for (const [stop, targetL] of SCALE_STOPS) {
    const diff = Math.abs(Number(stop) - targetL)
    if (diff < minDiff) {
      minDiff = diff
      anchorStop = Number(stop)
    }
  }

  for (const [stop, targetL] of SCALE_STOPS) {
    const stopNum = Number(stop)
    // Interpolate saturation: max at anchor, reduce toward edges
    const distFromAnchor = Math.abs(stopNum - anchorStop) / 500
    const satFactor = 1 - distFromAnchor * 0.6
    const s = clamp(seedHSL.s * satFactor, 3, 100)

    // Blend lightness between anchor and target
    const t = stopNum <= anchorStop
      ? stopNum / anchorStop
      : (stopNum - anchorStop) / (950 - anchorStop)

    const l = stopNum <= anchorStop
      ? lerp(seedHSL.l, targetL, 1 - t * 0.7)
      : lerp(seedHSL.l, targetL, t * 0.85)

    scale[stop] = hslToHex(seedHSL.h, s, clamp(l, 2, 98))
  }

  return scale
}

function generateBrandAccents(seedHSL: HSL): Record<string, string> {
  // Generate 6 harmonious accent colors by rotating hue
  const accents: Record<string, string> = {}
  const hues = [
    ['emerald', 0],
    ['blue', 50],
    ['purple', 105],
    ['amber', -35],
    ['indigo', 75],
    ['pink', -55],
  ] as const

  for (const [name, hueOffset] of hues) {
    const h = (seedHSL.h + hueOffset + 360) % 360
    // Accents are more saturated than the base
    const s = clamp(seedHSL.s * 1.3, 50, 95)
    // Accents sit at a medium lightness (around 55-65%)
    const l = 58
    accents[name] = hslToHex(h, s, l)
  }

  return accents
}

function generateChartPalette(seedHSL: HSL): string[] {
  // 10-color harmonious sequence — step hue around the wheel
  const palette: string[] = []
  for (let i = 0; i < 10; i++) {
    const h = (seedHSL.h + i * 36 + 360) % 360  // 36° steps = 10 colors around wheel
    const s = clamp(seedHSL.s + 10, 40, 90)
    // Alternate lightness for visual distinction
    const l = i % 2 === 0 ? 52 : 62
    palette.push(hslToHex(h, s, l))
  }
  return palette
}

function generateSemantic(seedHSL: HSL): Palette['semantic'] {
  return {
    success: hslToHex(150, 70, 48),   // fixed — green
    warning: hslToHex(45, 85, 55),     // fixed — amber
    error: hslToHex(0, 75, 55),        // fixed — red
    info: hslToHex(seedHSL.h, clamp(seedHSL.s * 0.8, 40, 80), 55),
  }
}

function generateSurfaceTokens(
  seedHSL: HSL,
  mode: 'dark' | 'light'
): SurfaceTokens {
  if (mode === 'dark') {
    // Dark mode — deep backgrounds, light text
    const bgHue = seedHSL.h
    return {
      app: hslToHex(bgHue, 15, 3.5),
      surface: hslToHex(bgHue, 12, 5),
      card: hslToHex(bgHue, 12, 5),
      panel: hslToHex(bgHue, 10, 8.5),
      'panel-hover': hslToHex(bgHue, 9, 11),
      'text-primary': '#f1f3f6',
      'text-secondary': '#94a3b8',
      'text-tertiary': '#64748b',
      'text-muted': '#475569',
      border: hslToHex(bgHue, 10, 14),
      'border-strong': hslToHex(bgHue, 8, 20),
      glass: `rgba(12, 13, 18, 0.92)`,
    }
  } else {
    // Light mode — light backgrounds, dark text
    const bgHue = seedHSL.h
    return {
      app: hslToHex(bgHue, 8, 96),
      surface: '#ffffff',
      card: '#ffffff',
      panel: hslToHex(bgHue, 8, 89),
      'panel-hover': hslToHex(bgHue, 6, 80),
      'text-primary': '#1b221f',
      'text-secondary': '#4b5b55',
      'text-tertiary': '#5f726b',
      'text-muted': '#7a8d85',
      border: hslToHex(bgHue, 5, 65),
      'border-strong': hslToHex(bgHue, 4, 52),
      glass: 'rgba(255, 255, 255, 0.92)',
    }
  }
}

function generatePalette(seedHex: string, mode: 'dark' | 'light' = 'dark'): Palette {
  const seedHSL = hexToHsl(seedHex)

  return {
    seed: seedHex,
    scale: generateScale(seedHSL),
    brand: generateBrandAccents(seedHSL),
    chart: generateChartPalette(seedHSL),
    semantic: generateSemantic(seedHSL),
    surfaces: {
      dark: generateSurfaceTokens(seedHSL, 'dark'),
      light: generateSurfaceTokens(seedHSL, 'light'),
    },
  }
}

// ── Output Formatters ──────────────────────────────────

function formatJson(palette: Palette): string {
  return JSON.stringify(palette, null, 2)
}

function formatCss(palette: Palette): string {
  let css = `/* Generated from seed: ${palette.seed} */\n`
  css += ':root {\n'

  // Scale
  for (const [stop, hex] of Object.entries(palette.scale)) {
    css += `  --color-brand-${stop}: ${hex};\n`
  }

  // Brand accents
  for (const [name, hex] of Object.entries(palette.brand)) {
    css += `  --color-accent-${name}: ${hex};\n`
  }

  // Semantic
  for (const [name, hex] of Object.entries(palette.semantic)) {
    css += `  --color-${name}: ${hex};\n`
  }

  // Chart
  palette.chart.forEach((hex, i) => {
    css += `  --color-chart-${i}: ${hex};\n`
  })

  // Dark surfaces
  css += '\n  /* Dark mode surfaces */\n'
  const dark = palette.surfaces.dark
  for (const [key, val] of Object.entries(dark)) {
    css += `  --color-${key}: ${val};\n`
  }

  css += '}\n\n'

  // Light mode override
  css += '.light {\n'
  const light = palette.surfaces.light
  for (const [key, val] of Object.entries(light)) {
    css += `  --color-${key}: ${val};\n`
  }
  css += '}\n'

  return css
}

function formatTailwind(palette: Palette): string {
  const colors: Record<string, string | Record<string, string>> = {}

  // Scale
  const brand: Record<string, string> = {}
  for (const [stop, hex] of Object.entries(palette.scale)) {
    brand[stop] = hex
  }
  colors['brand'] = brand

  // Accents
  for (const [name, hex] of Object.entries(palette.brand)) {
    colors[`accent-${name}`] = hex
  }

  // Semantic
  for (const [name, hex] of Object.entries(palette.semantic)) {
    colors[name] = hex
  }

  // Chart
  const chart: Record<string, string> = {}
  palette.chart.forEach((hex, i) => {
    chart[String(i)] = hex
  })
  colors['chart'] = chart

  // Surfaces
  colors['app'] = `var(--color-app)`
  colors['surface'] = `var(--color-surface)`
  colors['card'] = `var(--color-card)`
  colors['panel'] = `var(--color-panel)`
  colors['panel-hover'] = `var(--color-panel-hover)`
  colors['primary'] = `var(--color-text-primary)`
  colors['secondary'] = `var(--color-text-secondary)`
  colors['tertiary'] = `var(--color-text-tertiary)`
  colors['muted'] = `var(--color-text-muted)`
  colors['default'] = `var(--color-border)`
  colors['strong'] = `var(--color-border-strong)`
  colors['glass'] = `var(--color-glass)`

  return [
    '// Generated by scripts/generate-palette.ts',
    `// Seed: ${palette.seed}`,
    'export default {',
    '  theme: {',
    '    extend: {',
    '      colors: ' + JSON.stringify(colors, null, 6).replace(/^/gm, '      ').trimStart(),
    '    },',
    '  },',
    '}',
  ].join('\n')
}

// ── CLI Entry Point ────────────────────────────────────

function main() {
  const args = process.argv.slice(2)
  const seedHex = args.find(a => /^#?[0-9a-f]{6}$/i.test(a)) ?? '#14b8a6'
  const cleanSeed = seedHex.startsWith('#') ? seedHex : `#${seedHex}`
  const mode = args.includes('--mode') ? args[args.indexOf('--mode') + 1] as 'dark' | 'light' || 'dark' : 'dark'
  const output = args.includes('--output') ? args[args.indexOf('--output') + 1] as 'json' | 'css' | 'tailwind' || 'css' : 'css'
  const outDir = args.includes('--out-dir') ? args[args.indexOf('--out-dir') + 1] : null

  const palette = generatePalette(cleanSeed, mode)

  let body: string
  let ext: string
  switch (output) {
    case 'json':
      body = formatJson(palette)
      ext = 'json'
      break
    case 'tailwind':
      body = formatTailwind(palette)
      ext = 'js'
      break
    case 'css':
    default:
      body = formatCss(palette)
      ext = 'css'
      break
  }

  if (outDir) {
    mkdirSync(resolve(outDir), { recursive: true })
    const filename = `palette-${cleanSeed.replace('#', '')}.${ext}`
    writeFileSync(resolve(outDir, filename), body)
    console.log(`✓ Generated ${filename}`)
  } else {
    console.log(body)
  }

  // Also print a summary
  console.log('\n── Palette Summary ──')
  console.log(`Seed:       ${cleanSeed} (${JSON.stringify(hexToHsl(cleanSeed))})`)
  console.log(`Mode:       ${mode}`)
  console.log(`Scale:      11 steps (50–950)`)
  console.log(`Accents:    ${Object.keys(palette.brand).join(', ')}`)
  console.log(`Chart:      10 colors`)
  console.log(`Semantic:   ${Object.keys(palette.semantic).join(', ')}`)
  console.log(`Surfaces:   ${mode === 'dark' ? 'dark' : 'light'} (${Object.keys(palette.surfaces[mode]).length} tokens)`)
}

main()
