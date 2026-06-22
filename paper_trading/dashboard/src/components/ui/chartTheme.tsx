import type { CSSProperties } from 'react'
import { chart } from '../../design/color-system'

export const CHART_PALETTE = chart

export const CHART_PRIMARY = chart[0]
export const CHART_GRID = 'var(--color-border)'
export const CHART_AXIS = 'var(--color-text-tertiary)'

export const chartMargin = { top: 4, right: 8, left: 0, bottom: 0 }

export const axisTick = {
  fontSize: 10,
  fill: 'var(--color-text-tertiary)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 400,
}

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

export const cartesianGridProps = {
  stroke: 'var(--color-border)',
  strokeWidth: 0.3,
  vertical: false,
}

export const chartCursor = {
  stroke: 'var(--color-border-strong)',
  strokeWidth: 1,
  strokeDasharray: '4 4',
}

const defsId = 'chartGradient'

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
