import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts'
import { useGovernanceRadar } from '../../hooks/useGovernanceRadar'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import Badge from '../ui/Badge'
import ChartDataTable from '../ui/ChartDataTable'

/** Radar chart visualizing governance constraint scores across axes, with ranked bottleneck list and average validity impact. */
export default function GovernanceRadar() {
  const { axes, bottlenecks, avgValidityImpact } = useGovernanceRadar()

  const chartData = axes.map(a => ({
    axis: a.label,
    value: Math.round(a.value * 100),
    max: 100,
    description: a.description,
  }))
  const weakestAxis = chartData.length
    ? chartData.reduce((weakest, axis) => axis.value < weakest.value ? axis : weakest, chartData[0])
    : null
  const chartLabel = weakestAxis
    ? `Governance radar with ${chartData.length} axes. Weakest axis is ${weakestAxis.axis} at ${weakestAxis.value} percent.`
    : 'Governance radar chart'

  return (
    <Panel padding="lg">
      <SectionHeader
        title="Governance Constraint Analysis"
        accent="emerald"
        meta={
          bottlenecks.length > 0 ? (
            <span className="text-2xs text-tertiary font-mono bg-surface px-2 py-0.5 rounded border border-default">
              {bottlenecks.length} active constraints
            </span>
          ) : null
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Radar Chart */}
        <div className="lg:col-span-2">
          <div className="h-[260px]" role="img" aria-label={chartLabel}>
            <p className="sr-only">{chartLabel}</p>
            <ChartDataTable
              title="Governance constraint scores"
              columns={[
                { key: 'axis', label: 'Constraint' },
                { key: 'value', label: 'Score (%)', format: v => `${v}%` },
                { key: 'description', label: 'Description' },
              ]}
              data={chartData as unknown as Record<string, unknown>[]}
              summary={`Governance constraint radar with ${chartData.length} axes. Weakest: ${weakestAxis?.axis || 'N/A'} at ${weakestAxis?.value || 0}%.`}
            />
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={chartData} cx="50%" cy="50%" outerRadius="80%">
                <PolarGrid stroke="var(--color-border)" strokeWidth={0.75} />
                <PolarAngleAxis
                  dataKey="axis"
                  tick={{ fontSize: 10, fill: 'var(--color-text-secondary)', fontWeight: 500 }}
                />
                <PolarRadiusAxis
                  angle={90}
                  domain={[0, 100]}
                  tick={{ fontSize: 9, fill: 'var(--color-text-muted)' }}
                  tickCount={5}
                  axisLine={false}
                />
                <Radar
                  name="Health Score"
                  dataKey="value"
                  stroke="var(--color-accent-emerald)"
                  fill="var(--color-accent-emerald)"
                  fillOpacity={0.15}
                  strokeWidth={1.5}
                  animationDuration={400}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Bottleneck Ranking */}
        <div className="space-y-3">
          {bottlenecks.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs text-tertiary">
              No active constraints — all layers healthy
            </div>
          ) : (
            <>
              <p className="text-2xs font-semibold text-tertiary uppercase tracking-wider">
                Constraint Ranking
              </p>
              <div className="space-y-2">
                {bottlenecks.map(b => (
                  <div
                    key={b.layer}
                    className="flex items-start gap-2 px-2.5 py-2 rounded-lg border border-default bg-surface/30"
                  >
                    <span className="text-xs font-bold text-tertiary font-mono w-4 shrink-0">
                      {b.rank}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-medium text-primary">{b.layer}</span>
                        <Badge
                          variant={b.avgPenalty < -0.1 ? 'error' : 'warning'}
                          size="sm"
                        >
                          {(b.avgPenalty * 100).toFixed(0)}%
                        </Badge>
                      </div>
                      <p className="text-2xs text-tertiary mt-0.5 truncate">
                        {b.assets.join(', ')}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-accent-emerald/5 border border-accent-emerald/20 text-2xs">
                <span className="text-tertiary">Avg validity impact</span>
                <span className={`font-semibold font-mono ${avgValidityImpact >= -0.05 ? 'text-signal-long' : 'text-signal-short'}`}>
                  {(avgValidityImpact * 100).toFixed(1)}%
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </Panel>
  )
}
