import type { CSSProperties } from 'react'

export const CHART_PALETTE = [
  '#2dd4bf', '#60a5fa', '#fbbf24', '#f472b6', '#a78bfa',
  '#5eead4', '#93c5fd', '#fde68a', '#f9a8d4', '#c4b5fd',
] as const

export const CHART_PRIMARY = '#2dd4bf'
export const CHART_GRID = 'var(--color-border)'
export const CHART_AXIS = 'var(--color-text-tertiary)'

export const chartMargin = { top: 4, right: 8, left: 0, bottom: 0 }

export const axisTick = {
  fontSize: 9,
  fill: 'var(--color-text-tertiary)',
  fontFamily: 'var(--font-mono)',
}

export const tooltipStyle: CSSProperties = {
  background: 'var(--color-card)',
  border: '1px solid var(--color-border-strong)',
  borderRadius: '6px',
  fontSize: '11px',
  fontFamily: 'var(--font-mono)',
  boxShadow: 'var(--shadow-tooltip, 0 4px 20px rgba(0,0,0,0.5))',
  padding: '8px 10px',
  lineHeight: '1.5',
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
  strokeWidth: 0.5,
  vertical: false,
}

export const chartCursor = {
  stroke: 'var(--color-border-strong)',
  strokeWidth: 1,
  strokeDasharray: '3 3',
}

const defsId = 'chartGradient'

export function ChartGradientDefs({ id = defsId }: { id?: string }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={CHART_PRIMARY} stopOpacity={0.15} />
        <stop offset="100%" stopColor={CHART_PRIMARY} stopOpacity={0.01} />
      </linearGradient>
    </defs>
  )
}

export function getGradientFill(id = defsId): string {
  return `url(#${id})`
}
