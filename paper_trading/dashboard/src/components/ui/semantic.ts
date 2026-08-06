import { success, warning, error, accents, chart } from '../../design/color-system'

/**
 * Resolve a semantic color name to its design-token hex value.
 *
 * Components that need a raw CSS color (StatCard `accent`, ScoreBar `color`,
 * chart fills) should pass a semantic NAME here instead of a literal hex so the
 * whole app draws from the token system. Unknown names fall back to the raw
 * string, which keeps existing call sites working during migration.
 */
const SEMANTIC_COLORS: Record<string, string> = {
  green: success.DEFAULT,
  red: error.DEFAULT,
  yellow: warning.DEFAULT,
  blue: accents.blue,
  purple: accents.purple,
  amber: accents.amber,
  emerald: accents.emerald,
  indigo: accents.indigo,
  pink: accents.pink,
  orange: chart[7],
}

export function semanticColor(nameOrHex: string): string {
  return SEMANTIC_COLORS[nameOrHex] ?? nameOrHex
}
