/**
 * AssetListPanel — CommandCenter's sortable asset roster.
 *
 * Extracted from src/pages/CommandCenter.tsx (Commit 3.2). The page
 * re-renders on every poll (via useTradingState); the panel itself is
 * memoized so its sort state stays local until the user interacts
 * with the sort buttons or row click.
 *
 * Mobile (sm:hidden): card-list rendering for narrow viewports.
 * Desktop (hidden sm:block): dense row-per-asset rendering using
 * TradingAssetRow.
 */
import { memo } from 'react'
import { ArrowUpDown } from 'lucide-react'
import { useTradingState } from '../lib/trading-state/hook'
import type { SortKey } from '../lib/trading-state/selectors'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'
import TradingAssetRow from './TradingAssetRow'

const sortOptions: { key: SortKey; label: string }[] = [
  { key: 'risk', label: 'Risk' },
  { key: 'name', label: 'Name' },
  { key: 'pnl', label: 'PnL' },
  { key: 'exit_phase', label: 'Exit' },
]

function AssetListPanelInner({ onSelectAsset }: AssetListPanelProps) {
  const {
    assetList,
    sortKey,
    sortAsc,
    setSortKey,
    toggleSortDirection,
    isLoading,
  } = useTradingState()

  return (
    <Panel padding="md">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Assets</span>
        <div className="flex items-center gap-1">
          {sortOptions.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setSortKey(opt.key)}
              className={`text-[10px] px-1.5 py-1 sm:py-0.5 min-h-[32px] sm:min-h-0 rounded transition-colors ${
                sortKey === opt.key
                  ? 'bg-panel text-primary font-semibold'
                  : 'text-tertiary hover:text-secondary'
              }`}
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={toggleSortDirection}
            className="ml-1 p-1.5 sm:p-0.5 rounded hover:bg-panel transition-colors min-h-[32px] sm:min-h-0"
            title={sortAsc ? 'Ascending' : 'Descending'}
          >
            <ArrowUpDown className="w-3 h-3 text-tertiary" strokeWidth={1.5} />
          </button>
          <span className="ml-2 text-[10px] text-tertiary">{assetList.length} assets</span>
        </div>
      </div>
      {assetList.length === 0 && !isLoading ? (
        <EmptyState message="No asset data available" compact />
      ) : (
        <>
          {/* Mobile card-list */}
          <div className="sm:hidden space-y-2">
            {assetList.map((asset) => {
              const pnl = asset.pnl_state.unrealized
              const pnlCls = pnl >= 0 ? 'text-gov-green' : 'text-gov-red'
              const eff = asset.pnl_state.efficiency
              const effCls =
                eff === 'HIGH'
                  ? 'text-gov-green'
                  : eff === 'LOW'
                  ? 'text-gov-red'
                  : 'text-tertiary'
              const riskCls =
                asset.risk_state.level === 'HIGH'
                  ? 'text-gov-red'
                  : asset.risk_state.level === 'MEDIUM'
                  ? 'text-gov-yellow'
                  : 'text-gov-green'
              const exit = asset.exit_state
              const phaseLabel =
                exit.phase === 'BREAKEVEN'
                  ? 'BE'
                  : exit.phase === 'TRAILING'
                  ? 'Trail'
                  : exit.phase === 'DECAY'
                  ? 'Decay'
                  : 'Static'
              const exitCls =
                exit.phase === 'TRAILING'
                  ? 'text-gov-green'
                  : exit.phase === 'BREAKEVEN' || exit.phase === 'DECAY'
                  ? 'text-gov-yellow'
                  : 'text-tertiary'
              const driver = asset.risk_state.drivers[0]
              return (
                <button
                  key={asset.identity}
                  type="button"
                  onClick={() => onSelectAsset?.(asset.identity)}
                  className="w-full text-left rounded-lg border border-default bg-panel/50 px-3 py-2.5 active:scale-[0.99] transition-transform"
                >
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                    <div>
                      <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">
                        Asset
                      </dt>
                      <dd className="text-xs font-mono text-primary mt-0.5 truncate flex items-center gap-1.5">
                        {asset.identity}
                        {asset.direction && (
                          <span
                            className={`text-[10px] font-bold ${
                              asset.direction === 'LONG'
                                ? 'text-gov-green'
                                : 'text-gov-red'
                            }`}
                            aria-label={
                              asset.direction === 'LONG'
                                ? 'Long position'
                                : 'Short position'
                            }
                          >
                            {asset.direction === 'LONG' ? 'L' : 'S'}
                          </span>
                        )}
                      </dd>
                    </div>
                    <div className="text-right">
                      <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">
                        PnL
                      </dt>
                      <dd
                        className={`text-xs font-mono tabular-nums mt-0.5 font-semibold ${pnlCls}`}
                      >
                        {pnl >= 0 ? '+' : ''}
                        {pnl.toFixed(2)}
                        <span className={`text-[9px] ml-0.5 ${effCls}`}>
                          {eff === 'HIGH' ? 'H' : eff === 'LOW' ? 'L' : 'N'}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">
                        Exit
                      </dt>
                      <dd className={`text-xs font-mono tabular-nums mt-0.5 ${exitCls}`}>
                        {phaseLabel}
                        {exit.peak_mfe_r != null ? ` @ ${exit.peak_mfe_r.toFixed(2)}R` : ''}
                      </dd>
                    </div>
                    <div className="text-right">
                      <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">
                        Risk
                      </dt>
                      <dd className={`text-xs font-semibold mt-0.5 ${riskCls}`}>
                        {asset.risk_state.level}
                      </dd>
                      {driver && <dd className="text-[10px] text-tertiary truncate">{driver}</dd>}
                    </div>
                  </dl>
                  {asset.flags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2 pt-1.5 border-t border-default/50">
                      {asset.flags.slice(0, 2).map((f) => (
                        <span
                          key={f}
                          className="text-[10px] text-tertiary bg-surface/50 px-1.5 py-0.5 rounded"
                        >
                          {f.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              )
            })}
          </div>
          {/* Desktop table */}
          <div className="hidden sm:block">
            <div className="divide-y divide-border/50">
              <div className="flex items-center gap-2 px-2 pb-1 text-[11px] text-secondary font-medium uppercase tracking-wider">
                <span className="w-24">Asset</span>
                <span className="w-20 text-right">PnL</span>
                <span className="w-36">Exit</span>
                <span className="w-24">Risk</span>
                <span className="flex-1 text-right">Flags</span>
              </div>
              {assetList.map((asset) => (
                <TradingAssetRow
                  key={asset.identity}
                  asset={asset}
                  onSelect={onSelectAsset}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </Panel>
  )
}

interface AssetListPanelProps {
  onSelectAsset?: (name: string) => void
}

const AssetListPanel = memo(AssetListPanelInner)
export default AssetListPanel
