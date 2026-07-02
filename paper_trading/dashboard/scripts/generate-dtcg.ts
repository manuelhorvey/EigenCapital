import { writeFileSync, mkdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { rawTokens, tailwindOnly } from '../src/design/color-system.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../generated')

type Obj = Record<string, unknown>

function setDeep(obj: Obj, path: string[], value: unknown) {
  let cur = obj
  for (let i = 0; i < path.length - 1; i++) {
    cur[path[i]] ??= {}
    cur = cur[path[i]] as Obj
  }
  cur[path[path.length - 1]] = value
}

function leaf(value: string, type: string): Obj {
  return { $value: value, $type: type }
}

// ── Key → DTCG path + type routing ─────────────────

type Route = { path: string[]; type: string }

function route(key: string): Route | null {
  if (key.startsWith('color-')) {
    // Scale colors: color-teal-50 → [color, teal, 50]
    const scale = key.match(/^color-(teal|indigo|neutral)-(\d+)$/)
    if (scale) return { path: ['color', scale[1], scale[2]], type: 'color' }

    // Map special paths the same way as the tailwind generator
    const prefix = key.startsWith('color-gov-') ? ['color', ...key.replace('color-gov-', 'gov-').split('-')]
      : key === 'color-app' ? ['color', 'app']
      : key === 'color-surface' ? ['color', 'surface']
      : key === 'color-card' ? ['color', 'card']
      : key === 'color-panel' ? ['color', 'panel']
      : key === 'color-panel-hover' ? ['color', 'panel-hover']
      : key === 'color-text-primary' ? ['color', 'text', 'primary']
      : key === 'color-text-secondary' ? ['color', 'text', 'secondary']
      : key === 'color-text-tertiary' ? ['color', 'text', 'tertiary']
      : key === 'color-text-muted' ? ['color', 'text', 'muted']
      : key === 'color-border' ? ['color', 'border']
      : key === 'color-border-strong' ? ['color', 'border-strong']
      : key === 'color-glass' ? ['color', 'glass']
      : key.startsWith('color-accent-') ? ['color', 'accent', key.replace('color-accent-', '')]
      : key.startsWith('color-chart-') ? ['color', 'chart', key.replace('color-chart-', '')]
      : key.startsWith('color-gov-green') ? ['color', 'gov', 'green', key.replace('color-gov-green-', '').replace('color-gov-green', 'DEFAULT')]
      : key.startsWith('color-gov-yellow') ? ['color', 'gov', 'yellow', key.replace('color-gov-yellow-', '').replace('color-gov-yellow', 'DEFAULT')]
      : key.startsWith('color-gov-red') ? ['color', 'gov', 'red', key.replace('color-gov-red-', '').replace('color-gov-red', 'DEFAULT')]
      : key.startsWith('color-gov-init') ? ['color', 'gov', 'init', key.replace('color-gov-init-', '').replace('color-gov-init', 'DEFAULT')]
      : null

    if (prefix) return { path: prefix, type: 'color' }
    return null
  }

  if (key.startsWith('shadow-')) {
    return { path: ['shadow', key.replace('shadow-', '')], type: 'shadow' }
  }
  if (key.startsWith('spacing-')) {
    return { path: ['spacing', key.replace('spacing-', '').replace(/_/g, '.')], type: 'dimension' }
  }
  if (key.startsWith('font-') && !key.startsWith('font-size-')) {
    return { path: ['fontFamily', key.replace('font-', '')], type: 'fontFamily' }
  }
  if (key.startsWith('font-size-')) {
    return { path: ['fontSize', key.replace('font-size-', '')], type: 'dimension' }
  }
  if (key.startsWith('line-height-')) {
    return { path: ['lineHeight', key.replace('line-height-', '')], type: 'number' }
  }
  if (key.startsWith('radius-')) {
    return { path: ['borderRadius', key.replace('radius-', '')], type: 'dimension' }
  }
  if (key.startsWith('animation-')) {
    return { path: ['animation', key.replace('animation-', '').replace(/-/g, '')], type: 'string' }
  }

  return null
}

// ── Build groups for a token map ───────────────────

function buildGroup(source: Record<string, string>, groupLabel: string): Obj {
  const group: Obj = {}
  for (const [key, value] of Object.entries(source)) {
    const r = route(key)
    if (r) {
      setDeep(group, [...r.path], leaf(value, r.type))
    }
  }
  return { [groupLabel]: group }
}

// ── Assemble full DTCG document ───────────────────

const dtcg: Obj = {
  $schema: 'https://design-tokens.github.io/community-group/format/',
  ...buildGroup(rawTokens, 'dark'),
}

// ── Write ──────────────────────────────────────────

mkdirSync(OUT, { recursive: true })
writeFileSync(resolve(OUT, 'tokens.json'), JSON.stringify(dtcg, null, 2) + '\n')

console.log('✓ generated/tokens.json')
