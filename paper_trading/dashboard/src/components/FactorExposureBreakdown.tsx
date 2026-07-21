import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import ChartDataTable from './ui/ChartDataTable'
import { Skeleton } from './ui/Skeleton'

function exposureColor(exposure: number, violation: string | null): string {
  if (violation) return 'var(--color-signal-short)'
  if (exposure > 0.15) return 'var(--color-signal-warn)'
  if (exposure < -0.15) return 'var(--color-signal-warn)'
  return 'var(--color-signal-long)'
}

/** Factor exposure bars with centered-zero visualization and violation highlights. */
export default function FactorExposureBreakdown() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const fe = portfolio?.factor_exposures

  const rows = useMemo(() => {
    if (!fe?.exposures) return null
    return Object.entries(fe.exposures)
      .map(([factor, exposure]) => {
        const viol = fe.violations?.[factor]
        return { factor, exposure, violation: viol?.violation ?? null }
      })
      .sort((a, b) => Math.abs(b.exposure) - Math.abs(a.exposure))
  }, [fe])

  if (!fe) return <Panel padding="md"><Skeleton className="h-24 rounded" shimmer /></Panel>

  return (
    <Panel padding="md">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">Factor Exposures</span>
          {!fe.within_limits && (
            <span className="text-[10px] font-bold text-signal-short bg-signal-short/10 px-2 py-0.5 rounded-full">
              {fe.n_violations} violation{fe.n_violations !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <ChartDataTable
          title="Factor Exposures"
          columns={[
            { key: 'factor', label: 'Factor' },
            { key: 'exposure', label: 'Exposure (%)', format: v => `${(Number(v) * 100).toFixed(1)}%` },
            { key: 'violation', label: 'Violation', format: (v: unknown): string => String(v ?? '') || '—' },
          ]}
          data={rows as unknown as Record<string, unknown>[]}
          summary={`Factor exposures for ${rows?.length || 0} factors`}
        />
        <div className="space-y-1.5">
          {rows?.map(({ factor, exposure, violation }) => {
            const pct = (exposure * 100).toFixed(1)
            const color = exposureColor(exposure, violation)
            const barWidth = `${Math.min(Math.abs(exposure) * 100, 100)}%`
            const isNeg = exposure < 0
            return (
              <div key={factor} className="flex items-center gap-2 text-xs">
                <span className="w-20 shrink-0 text-tertiary font-mono">{factor}</span>
                <div className="flex-1 h-4 bg-panel rounded-full overflow-hidden relative">
                  <div
                    className="absolute top-0 bottom-0 w-px bg-border"
                    style={{ left: '50%' }}
                  />
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: barWidth,
                      backgroundColor: color,
                      marginLeft: isNeg ? `calc(50% - ${barWidth})` : '50%',
                    }}
                  />
                </div>
                <span
                  className="w-14 text-right font-mono shrink-0"
                  style={{ color }}
                >
                  {isNeg ? '' : '+'}{pct}%
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </Panel>
  )
}
