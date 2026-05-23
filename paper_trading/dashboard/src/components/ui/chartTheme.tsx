import type { CSSProperties } from 'react'

export const CHART_PALETTE = [
  '#34d399',
  '#60a5fa',
  '#fbbf24',
  '#f472b6',
  '#a78bfa',
  '#2dd4bf',
  '#fb923c',
  '#94a3b8',
  '#e879f9',
  '#22d3ee',
  '#f87171',
] as const

export const CHART_PRIMARY = '#34d399'
export const CHART_GRID = 'var(--color-border)'
export const CHART_AXIS = 'var(--color-text-tertiary)'

export const chartMargin = { top: 8, right: 12, left: 4, bottom: 4 }

export const axisTick = { fontSize: 10, fill: CHART_AXIS, fontFamily: 'var(--font-mono)' }

export const tooltipStyle: CSSProperties = {
  background: 'var(--color-card)',
  border: '1px solid var(--color-border-strong)',
  borderRadius: '6px',
  fontSize: '11px',
  fontFamily: 'var(--font-mono)',
  boxShadow: 'var(--shadow-panel)',
  padding: '8px 10px',
}

export const tooltipLabelStyle: CSSProperties = {
  color: 'var(--color-text-secondary)',
  fontWeight: 600,
  marginBottom: 4,
  fontSize: '10px',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
}

export const cartesianGridProps = {
  strokeDasharray: '3 3',
  stroke: 'var(--color-panel)',
  vertical: false,
}

const defsId = 'chartGradient'

export function ChartGradientDefs({ id = defsId }: { id?: string }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={CHART_PRIMARY} stopOpacity={0.25} />
        <stop offset="100%" stopColor={CHART_PRIMARY} stopOpacity={0.01} />
      </linearGradient>
    </defs>
  )
}

export function getGradientFill(id = defsId): string {
  return `url(#${id})`
}
