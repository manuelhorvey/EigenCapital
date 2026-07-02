import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
import EmptyState from './ui/EmptyState'

export default function LiveSharpeCard() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const ls = portfolio?.live_sharpe

  const cards = useMemo(() => {
    if (!ls?.available) return null

    const items = []

    if (ls.cycle_level) {
      items.push({
        label: 'Cycle Sharpe (adj)',
        value: ls.cycle_level.sharpe_adj.toFixed(2),
        sub: `ρ=${ls.cycle_level.autocorrelation.toFixed(2)} · ${ls.cycle_level.n_cycles} cycles`,
        accent: ls.cycle_level.sharpe_adj >= 1 ? '#22c55e' : ls.cycle_level.sharpe_adj >= 0 ? '#eab308' : '#ef4444',
      })
    }

    if (ls.daily_level) {
      for (const [window, d] of Object.entries(ls.daily_level)) {
        if (d == null) continue
        items.push({
          label: `${window} Sharpe`,
          value: d.sharpe_adj.toFixed(2),
          sub: `PSR ${(d.psr_gt_0 * 100).toFixed(0)}% · ${d.n_days}d`,
          accent: d.sharpe_adj >= 1 ? '#22c55e' : d.sharpe_adj >= 0 ? '#eab308' : '#ef4444',
        })
      }
    }

    if (ls.portfolio) {
      items.push({
        label: 'Total Return',
        value: `${(ls.portfolio.total_return_pct >= 0 ? '+' : '')}${ls.portfolio.total_return_pct.toFixed(2)}%`,
        sub: `DD ${(ls.portfolio.max_drawdown_pct ?? 0).toFixed(2)}%`,
        accent: ls.portfolio.total_return_pct >= 0 ? '#22c55e' : '#ef4444',
      })
    }

    if (ls.slippage?.available) {
      items.push({
        label: 'Slippage RMS',
        value: `${ls.slippage.slippage_rms_pct?.toFixed(2)}%`,
        sub: `p90 ${ls.slippage.p90_gap_pct?.toFixed(2)}% · ${ls.slippage.n_samples} samples`,
        accent: (ls.slippage.slippage_rms_pct ?? 0) < 0.5 ? '#22c55e' : '#eab308',
      })
    }

    return items.length > 0 ? items : null
  }, [ls])

  if (!ls?.available) {
    return (
      <Panel padding="md">
        <EmptyState message={ls?.reason ?? 'Live Sharpe unavailable'} compact />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
      {cards?.map(c => (
        <StatCard key={c.label} label={c.label} value={c.value} sub={c.sub} accent={c.accent} />
      ))}
    </div>
  )
}
