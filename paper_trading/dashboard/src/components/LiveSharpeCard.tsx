import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
import EmptyState from './ui/EmptyState'
import { gridMetric4, GRID_GAP } from '../design/grid'

/** Live Sharpe ratio cards with cycle-level, daily-window, and slippage metrics.
 *
 * Methodology
 * -----------
 * - **Cycle Sharpe (adj)**: Autocorrelation-adjusted Sharpe across engine cycles
 *   (~30s bars). The adjustment accounts for serial correlation in cycle-level
 *   returns using ρ (autocorrelation estimate). Formula: Sharpe_adj = Sharpe_raw ×
 *   sqrt((1 - ρ) / (1 + ρ)). Displayed with n_cycles for context.
 *
 * - **Window Sharpe**: Daily returns aggregated over rolling windows (7d, 30d, 90d).
 *   Includes Probabilistic Sharpe Ratio (PSR) — probability that the true Sharpe
 *   exceeds 0, accounting for non-normality via higher moments (skew, kurtosis).
 *   Displayed with n_days for sample size context.
 *
 * - **Per-asset Sharpe** (displayed in SignalsTable / AssetDetailPanel): Computed
 *   from individual trade PnL history using autocorrelation-adjusted formula.
 *   Treat with caution when n_trades < 20 (see SignalsTable.tsx comments).
 *
 * All Sharpe values use risk-free rate = 0 (consistent with backtest methodology
 * in scripts/backtest/backtest_pnl.py).
 */
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
        accent: ls.cycle_level.sharpe_adj >= 1 ? 'var(--color-gov-green)' : ls.cycle_level.sharpe_adj >= 0 ? 'var(--color-gov-yellow)' : 'var(--color-gov-red)',
      })
    }

    if (ls.daily_level) {
      for (const [window, d] of Object.entries(ls.daily_level)) {
        if (d == null) continue
        items.push({
          label: `${window} Sharpe`,
          value: d.sharpe_adj.toFixed(2),
          sub: `PSR ${(d.psr_gt_0 * 100).toFixed(0)}% · ${d.n_days}d`,
          accent: d.sharpe_adj >= 1 ? 'var(--color-gov-green)' : d.sharpe_adj >= 0 ? 'var(--color-gov-yellow)' : 'var(--color-gov-red)',
        })
      }
    }

    if (ls.portfolio) {
      items.push({
        label: 'Total Return',
        value: `${(ls.portfolio.total_return_pct >= 0 ? '+' : '')}${ls.portfolio.total_return_pct.toFixed(2)}%`,
        sub: `DD ${(ls.portfolio.max_drawdown_pct ?? 0).toFixed(2)}%`,
        accent: ls.portfolio.total_return_pct >= 0 ? 'var(--color-gov-green)' : 'var(--color-gov-red)',
      })
    }

    if (ls.slippage?.available) {
      items.push({
        label: 'Slippage RMS',
        value: `${ls.slippage.model_timing_gap_pct?.toFixed(2)}%`,
        sub: `p90 ${ls.slippage.p90_gap_pct?.toFixed(2)}% · ${ls.slippage.n_samples} samples`,
        accent: (ls.slippage.model_timing_gap_pct ?? 0) < 0.5 ? 'var(--color-gov-green)' : 'var(--color-gov-yellow)',
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
    <div className={`${gridMetric4()} ${GRID_GAP}`}>
      {cards?.map(c => (
        <StatCard key={c.label} label={c.label} value={c.value} sub={c.sub} accent={c.accent} />
      ))}
    </div>
  )
}
