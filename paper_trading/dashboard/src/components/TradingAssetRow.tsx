import { memo } from 'react'
import type { AssetTradingState } from '../lib/trading-state/types'
import Badge from './ui/Badge'
import ExitPhaseIndicator from './ExitPhaseIndicator'

interface TradingAssetRowProps {
  asset: AssetTradingState
  onSelect?: (name: string) => void
}

/**
 * Operator-trading asset row: dense mono layout used by the
 * `Positions` panel on CommandCenter (/). One row = one tradable asset
 * with unrealized P&L, exit phase, risk signal, and the leading
 * two risk flags, ordered by the panel-level sort.
 *
 * Visual contract:
 *   - click anywhere on the row -> invokes onSelect(asset.identity)
 *   - row height fixed by column widths; long flags truncate
 *   - direction L/S appears as a 1-char Badge next to the asset name
 *   - risk uses a dot variant of <Badge variant="success|warning|error">
 *   - the row is a <button> so it has the same keyboard flow as the
 *     rest of the header chrome
 *
 * Extracted from pages/CommandCenter.tsx in audit item #7 so the
 * page file becomes shorter and other workspaces (TradingWorkspace,
 * RiskWorkspace) can render the same row shape without duplicating
 * a 60-line component.
 */
const TradingAssetRow = memo(function TradingAssetRow({ asset, onSelect }: TradingAssetRowProps) {
  const pnlColor = asset.pnl_state.unrealized >= 0
    ? 'text-gov-green'
    : 'text-gov-red'

  return (
    <button
      type="button"
      onClick={() => onSelect?.(asset.identity)}
      className="w-full flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-panel/60 transition-colors border border-transparent hover:border-default group text-left"
    >
      {/* Asset name + direction */}
      <div className="flex items-center gap-2 w-28 shrink-0">
        <span className="text-xs font-semibold text-primary font-mono">{asset.identity}</span>
        {asset.direction && (
          <Badge
            variant={asset.direction === 'LONG' ? 'success' : 'error'}
            size="sm"
            icon={asset.direction === 'LONG' ? 'long' : 'short'}
          >
            {asset.direction === 'LONG' ? 'L' : 'S'}
          </Badge>
        )}
      </div>

      {/* PnL */}
      <div className="w-20 shrink-0 text-right">
        <span className={`text-xs font-mono tabular-nums font-semibold ${pnlColor}`}>
          {asset.pnl_state.unrealized >= 0 ? '+' : ''}{asset.pnl_state.unrealized.toFixed(2)}
        </span>
      </div>

      {/* Exit phase */}
      <div className="w-36 shrink-0">
        <ExitPhaseIndicator
          phase={asset.exit_state.phase}
          slIsDynamic={asset.exit_state.sl_is_dynamic}
          peakMfeR={asset.exit_state.peak_mfe_r}
        />
      </div>

      {/* Risk level */}
      <div className="w-20 shrink-0">
        <Badge
          variant={
            asset.risk_state.level === 'HIGH' ? 'error'
            : asset.risk_state.level === 'MEDIUM' ? 'warning'
            : 'success'
          }
          size="sm"
          dot
        >
          {asset.risk_state.level}
        </Badge>
      </div>

      {/* Flags */}
      <div className="flex-1 flex items-center gap-1 min-w-0">
        {asset.flags.slice(0, 2).map((flag) => (
          <Badge key={flag} variant="neutral" size="sm">
            {flag.replace(/_/g, ' ')}
          </Badge>
        ))}
      </div>
    </button>
  )
})

export default TradingAssetRow
