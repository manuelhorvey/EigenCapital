import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import Gauge from './ui/Gauge'
import { Skeleton } from './ui/Skeleton'

/** Position concentration gauge showing long/short skew and alert status. */
export default function PositionConcentrationPanel() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const pc = portfolio?.position_concentration

  if (!pc) return <Panel padding="md"><Skeleton className="h-20 rounded" shimmer /></Panel>

  const skewPct = Math.abs(pc.skew)
  const isAlert = pc.alert
  const dominantLabel = pc.dominant_side === 'short' ? 'Net Short' : pc.dominant_side === 'long' ? 'Net Long' : 'Balanced'

  return (
    <Panel padding="md">
      <div className="flex items-center gap-4">
        <Gauge
          label="Skew"
          value={skewPct}
          size={72}
          color={isAlert ? 'var(--color-gov-red)' : skewPct > 0.5 ? 'var(--color-gov-yellow)' : 'var(--color-gov-green)'}
        />
        <div className="min-w-0 space-y-1">
          <div className="text-xs font-semibold text-primary">{dominantLabel}</div>
          <div className="flex gap-3 text-2xs text-tertiary font-mono">
            <span>L {pc.long}</span>
            <span>S {pc.short}</span>
            <span>T {pc.total}</span>
          </div>
          {isAlert && (
            <span aria-live="polite" className="inline-flex items-center gap-1 text-[10px] font-bold text-gov-red bg-gov-red/10 px-2 py-0.5 rounded-full">
              Skew exceeds {((pc.threshold ?? 0.75) * 100).toFixed(0)}% threshold
            </span>
          )}
        </div>
      </div>
    </Panel>
  )
}
