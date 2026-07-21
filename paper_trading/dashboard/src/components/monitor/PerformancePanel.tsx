import React from 'react'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'

interface Metric {
  label: string
  value: string
  target?: string
  status?: 'good' | 'warning' | 'critical'
}

interface PerformancePanelProps {
  metrics: Metric[]
}

function statusColor(status: Metric['status']): string {
  switch (status) {
    case 'good': return 'text-signal-long'
    case 'warning': return 'text-signal-warn'
    case 'critical': return 'text-signal-short'
    default: return 'text-secondary'
  }
}

/** Panel displaying system performance metrics as a grid of stat cards with color-coded statuses.
 * @param {Metric[]} metrics - Array of metric objects with label, value, optional target and status */
const PerformancePanel = /*#__PURE__*/ React.memo<PerformancePanelProps>(function PerformancePanel({ metrics }) {
  if (metrics.length === 0) return null

  return (
    <Panel padding="md">
      <SectionHeader title="System Performance" accent="emerald" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {metrics.map(m => (
          <div key={m.label} className="border border-default rounded-lg px-2.5 py-2 bg-surface/30">
            <p className="text-2xs text-tertiary font-medium uppercase tracking-wider mb-0.5">{m.label}</p>
            <p className={`text-xs font-bold font-mono tabular-nums ${statusColor(m.status)}`}>
              {m.value}
            </p>
            {m.target && (
              <p className="text-[10px] text-muted font-mono tabular-nums">target {m.target}</p>
            )}
          </div>
        ))}
      </div>
    </Panel>
  )
})

export default PerformancePanel
