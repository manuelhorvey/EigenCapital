import type { CSSProperties } from 'react'
import { chart } from '../../design/color-system'

export const CHART_PALETTE = chart

export const CHART_PRIMARY = chart[0]
export const CHART_GRID = 'var(--color-border)'
export const CHART_AXIS = 'var(--color-text-tertiary)'

// Optimized margins — tighter than standard Recharts defaults for the
// dense terminal-style display. Left/bottom = 0 because axis ticks are
// formatted to avoid collision; right margin reserved for last tick.
export const chartMargin = { top: 4, right: 8, left: 0, bottom: 0 }

// ── Axis tokens ────────────────────────────────────────────
export const axisTick = {
  fontSize: 10,
  fill: 'var(--color-text-tertiary)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 400,
}

/** Axis tick configuration for compact charts */
export const axisTickCompact = {
  ...axisTick,
  fontSize: 9,
}

/** Axis style for y-axis (right-aligned, monospace, tabular figures) */
export const axisStyle: CSSProperties = {
  fontSize: 10,
  fill: 'var(--color-text-muted)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 400,
}

// ── Tooltip tokens ─────────────────────────────────────────
export const tooltipStyle: CSSProperties = {
  background: 'var(--color-card)',
  border: '1.5px solid var(--color-border-strong)',
  borderRadius: '6px',
  fontSize: '11px',
  fontFamily: 'var(--font-mono)',
  boxShadow: 'var(--shadow-tooltip, 0 4px 20px rgba(0,0,0,0.5))',
  padding: '10px 12px',
  lineHeight: '1.5',
  backdropFilter: 'blur(4px)',
}

export const tooltipLabelStyle: CSSProperties = {
  color: 'var(--color-text-secondary)',
  fontWeight: 600,
  marginBottom: 4,
  fontSize: '11px',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
}

/** Tooltip item style (value rows) */
export const tooltipItemStyle: CSSProperties = {
  color: 'var(--color-text-primary)',
  fontSize: '11px',
  paddingBottom: 2,
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
}

// ── Grid / Cursor tokens ───────────────────────────────────
export const cartesianGridProps = {
  stroke: 'var(--color-border)',
  strokeWidth: 0.3,
  vertical: false,
}

/** Denser grid for compact chart displays */
export const cartesianGridPropsCompact = {
  ...cartesianGridProps,
  strokeDasharray: '2 2',
}

export const chartCursor = {
  stroke: 'var(--color-border-strong)',
  strokeWidth: 1,
  strokeDasharray: '4 4',
}

/** Active dot style (the dot that appears on hover interaction) */
export const activeDot = {
  r: 4,
  strokeWidth: 2,
  stroke: 'var(--color-accent-emerald)',
  fill: 'var(--color-card)',
}

/** Active dot for short/sell signals */
export const activeDotShort = {
  ...activeDot,
  stroke: 'var(--color-signal-short)',
}

/** Reference line style */
export const referenceLine = {
  stroke: 'var(--color-text-muted)',
  strokeDasharray: '4 4',
  strokeWidth: 1,
}

// ── Gradient defs ──────────────────────────────────────────
const defsId = 'chartGradient'

/** Recharts `<defs>` gradient block for area chart fills. Inline in SVG, use with getGradientFill(). */
export function ChartGradientDefs({ id = defsId }: { id?: string }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={CHART_PRIMARY} stopOpacity={0.2} />
        <stop offset="100%" stopColor={CHART_PRIMARY} stopOpacity={0.01} />
      </linearGradient>
    </defs>
  )
}

export function getGradientFill(id = defsId): string {
  return `url(#${id})`
}
