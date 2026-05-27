import { useShadowTrades } from '../../hooks/useShadowTrades'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { TableSkeleton } from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'

export default function ShadowComparisonTable() {
  const { data: shadows, isPending } = useShadowTrades(20)

  if (isPending) return <TableSkeleton rows={5} />
  if (!shadows || shadows.length === 0) return <Panel><EmptyState message="No shadow trades recorded yet" compact /></Panel>

  const divergences = shadows.map(s => ({
    ...s,
    reasonDiverges: s.exit_reason !== s.live_exit_reason,
    rDelta: s.realized_r - s.live_realized_r,
  }))

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Shadow vs Live Comparison"
        accent="purple"
        meta={
          <span className="text-2xs text-tertiary">
            {divergences.filter(d => d.reasonDiverges).length} diverging / {divergences.length} total
          </span>
        }
      />
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[700px]">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2 pr-2">Asset</th>
              <th className="table-header text-left py-2 pr-2">Config</th>
              <th className="table-header text-right py-2 pr-2">Shadow R</th>
              <th className="table-header text-right py-2 pr-2">Live R</th>
              <th className="table-header text-right py-2 pr-2">ΔR</th>
              <th className="table-header text-left py-2 pr-2">Shadow Exit</th>
              <th className="table-header text-left py-2 pr-2">Live Exit</th>
              <th className="table-header text-right py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {divergences.map((s, i) => (
              <tr key={i} className="border-b border-default/40 table-row-hover">
                <td className="py-2 pr-2 font-mono font-medium text-primary">{s.asset}</td>
                <td className="py-2 pr-2">
                  <span className="signal-pill signal-pill-flat text-2xs">{s.alt_label}</span>
                </td>
                <td className={`py-2 pr-2 text-right font-mono tabular-nums ${s.realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                  {s.realized_r.toFixed(2)}
                </td>
                <td className={`py-2 pr-2 text-right font-mono tabular-nums ${s.live_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                  {s.live_realized_r.toFixed(2)}
                </td>
                <td className={`py-2 pr-2 text-right font-mono tabular-nums ${s.rDelta > 0.5 ? 'text-gov-green' : s.rDelta < -0.5 ? 'text-gov-red' : 'text-tertiary'}`}>
                  {s.rDelta > 0 ? '+' : ''}{s.rDelta.toFixed(2)}
                </td>
                <td className="py-2 pr-2">
                  <span className={`signal-pill ${s.exit_reason === 'tp' ? 'signal-pill-buy' : 'signal-pill-sell'}`}>
                    {s.exit_reason}
                  </span>
                </td>
                <td className="py-2 pr-2">
                  <span className={`signal-pill ${s.live_exit_reason === 'tp' ? 'signal-pill-buy' : s.live_exit_reason === 'sl' ? 'signal-pill-sell' : 'signal-pill-flat'}`}>
                    {s.live_exit_reason}
                  </span>
                </td>
                <td className="py-2 text-right">
                  {s.reasonDiverges ? (
                    <span className="text-2xs font-medium text-gov-red">DIVERGE</span>
                  ) : (
                    <span className="text-2xs font-medium text-gov-green">MATCH</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
