import { useTradeOutcomes } from '../hooks/useTradeOutcomes'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import StatCard from './ui/StatCard'
import Button from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import SltpGauge from './trades/SltpGauge'

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function r2(v: number): string {
  return v.toFixed(2)
}

/** Aggregated trade outcome metrics with per-asset breakdown (TP/SL/flip rates, avg R, win rate, PF). */
export default function TradeOutcomes() {
  const { outcomes, isPending, isError, refetch } = useTradeOutcomes()

  if (isPending) {
    return (
      <Panel className="animate-pulse">
        <SectionHeader title="Trade Outcomes" accent="emerald" />
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
        <SectionHeader title="Trade Outcomes" accent="emerald" />
        <div className="flex flex-col items-center py-8 gap-3">
          <div className="text-xs text-tertiary">Failed to load outcome data</div>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>Retry</Button>
        </div>
      </Panel>
    )
  }

  const { overall, by_asset: byAsset } = outcomes
  const hasData = byAsset.length > 0

  return (
    <Panel padding="lg">
      <SectionHeader title="Trade Outcomes" accent="emerald" border />
      {!hasData ? (
        <div className="text-xs text-tertiary text-center py-8">No trades closed yet</div>
      ) : (
        <>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5 mb-5">
            <StatCard variant="kpi" label="TP Hit Rate" value={pct(overall.tp_rate)} accent="var(--color-gov-green)" />
            <StatCard variant="kpi" label="SL Hit Rate" value={pct(overall.sl_rate)} accent="var(--color-gov-red)" />
            <StatCard variant="kpi" label="Flip Rate" value={pct(overall.signal_flip_rate)} accent="var(--color-gov-yellow)" />
            <StatCard variant="kpi" label="Avg R" value={r2(overall.avg_r)} accent={overall.avg_r >= 0 ? 'var(--color-gov-green)' : 'var(--color-gov-red)'} />
            <StatCard variant="kpi" label="Win Rate" value={pct(overall.win_rate)} accent="var(--color-text-secondary)" />
            <StatCard variant="kpi" label="Profit Factor" value={overall.profit_factor !== null ? r2(overall.profit_factor) : '—'} accent="var(--color-text-secondary)" />
          </div>

          <div className="overflow-x-auto">
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

          {/* Mobile card list fallback */}
          <div className="sm:hidden space-y-2 mt-3">
            {byAsset.map((a) => (
              <div key={a.asset} className="bg-panel/60 border border-default rounded-lg p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-semibold text-primary">{a.asset}</span>
                  <span className="text-2xs text-tertiary">{a.n_trades} trades</span>
                </div>
                <div className="flex items-center gap-2 text-2xs">
                  <span className={a.tp_rate >= 0.2 ? 'text-gov-green' : 'text-gov-yellow'}>
                    TP {pct(a.tp_rate)}
                  </span>
                  <span className={a.sl_rate <= 0.6 ? 'text-tertiary' : 'text-gov-red'}>
                    SL {pct(a.sl_rate)}
                  </span>
                  <span className="text-tertiary">Flip {pct(a.signal_flip_rate)}</span>
                </div>
                <div className="flex items-center gap-3 text-2xs">
                  <span className={a.avg_r >= 0 ? 'text-gov-green' : 'text-gov-red'}>
                    Avg R {r2(a.avg_r)}
                  </span>
                  <span className="text-secondary">Win {pct(a.win_rate)}</span>
                  <span className="text-secondary">PF {a.profit_factor !== null ? r2(a.profit_factor) : '—'}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  )
}
