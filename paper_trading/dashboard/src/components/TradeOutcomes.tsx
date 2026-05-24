import { useTradeOutcomes } from '../hooks/useTradeOutcomes'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import KpiCard from './ui/KpiCard'
import { Skeleton } from './ui/Skeleton'
import SltpGauge from './ui/SltpGauge'

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function r2(v: number): string {
  return v.toFixed(2)
}

export default function TradeOutcomes() {
  const { outcomes, isPending, isError } = useTradeOutcomes()

  if (isPending) {
    return (
      <Panel className="animate-pulse">
        <SectionHeader title="Trade Outcomes" accent="purple" />
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-panel rounded-lg p-3">
              <Skeleton className="h-3 w-full mb-2 rounded" />
              <Skeleton className="h-5 w-3/4 rounded" />
            </div>
          ))}
        </div>
        <Skeleton className="h-24 w-full rounded" />
      </Panel>
    )
  }

  if (isError || !outcomes) {
    return (
      <Panel>
        <SectionHeader title="Trade Outcomes" accent="purple" />
        <div className="text-xs text-tertiary text-center py-8">Failed to load outcome data</div>
      </Panel>
    )
  }

  const { overall, by_asset: byAsset } = outcomes
  const hasData = byAsset.length > 0

  return (
    <Panel padding="lg">
      <SectionHeader title="Trade Outcomes" accent="purple" border />
      {!hasData ? (
        <div className="text-xs text-tertiary text-center py-8">No trades closed yet</div>
      ) : (
        <>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5 mb-5">
            <KpiCard label="TP Hit Rate" value={pct(overall.tp_rate)} color="text-gov-green" />
            <KpiCard label="SL Hit Rate" value={pct(overall.sl_rate)} color="text-gov-red" />
            <KpiCard label="Flip Rate" value={pct(overall.signal_flip_rate)} color="text-gov-yellow" />
            <KpiCard label="Avg R" value={r2(overall.avg_r)} color={overall.avg_r >= 0 ? 'text-gov-green' : 'text-gov-red'} />
            <KpiCard label="Win Rate" value={pct(overall.win_rate)} color="text-accent-blue" />
            <KpiCard label="Profit Factor" value={overall.profit_factor !== null ? r2(overall.profit_factor) : '—'} color="text-accent-purple" />
          </div>

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs min-w-[680px]">
              <thead>
                <tr className="border-b border-default">
                  <th className="table-header text-left py-2 pr-2">Asset</th>
                  <th className="table-header text-right py-2 px-2">Trades</th>
                  <th className="table-header text-left py-2 px-2">Hit Rates</th>
                  <th className="table-header text-right py-2 px-2">TP%</th>
                  <th className="table-header text-right py-2 px-2">SL%</th>
                  <th className="table-header text-right py-2 px-2">Flip%</th>
                  <th className="table-header text-right py-2 px-2">Avg R</th>
                  <th className="table-header text-right py-2 px-2">Win%</th>
                  <th className="table-header text-right py-2 pl-2">PF</th>
                </tr>
              </thead>
              <tbody>
                {byAsset.map((a) => (
                  <tr key={a.asset} className="border-b border-default/40 table-row-hover">
                    <td className="py-2 pr-2 font-medium text-primary font-mono text-xs">{a.asset}</td>
                    <td className="text-right py-2 px-2 text-secondary font-mono tabular-nums">{a.n_trades}</td>
                    <td className="py-2 px-2">
                      <SltpGauge tpRate={a.tp_rate} slRate={a.sl_rate} flipRate={a.signal_flip_rate} />
                    </td>
                    <td className={`text-right py-2 px-2 font-mono tabular-nums ${a.tp_rate >= 0.2 ? 'text-gov-green' : 'text-gov-yellow'}`}>
                      {pct(a.tp_rate)}
                    </td>
                    <td className={`text-right py-2 px-2 font-mono tabular-nums ${a.sl_rate <= 0.6 ? 'text-secondary' : 'text-gov-red'}`}>
                      {pct(a.sl_rate)}
                    </td>
                    <td className="text-right py-2 px-2 text-tertiary font-mono tabular-nums">{pct(a.signal_flip_rate)}</td>
                    <td className={`text-right py-2 px-2 font-mono tabular-nums ${a.avg_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                      {r2(a.avg_r)}
                    </td>
                    <td className="text-right py-2 px-2 text-secondary font-mono tabular-nums">{pct(a.win_rate)}</td>
                    <td className="text-right py-2 pl-2 text-secondary font-mono tabular-nums">
                      {a.profit_factor !== null ? r2(a.profit_factor) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  )
}
