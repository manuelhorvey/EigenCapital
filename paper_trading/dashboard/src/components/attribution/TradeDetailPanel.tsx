import { X } from 'lucide-react'
import type { TradeAttributionRecord } from '../../types/attribution'
import { computeDomainScores } from './domainScores'
import { BarRow } from '../ui/ProgressBar'

interface TradeDetailPanelProps {
  trade: TradeAttributionRecord
  onClose: () => void
}

/** Expandable detail panel showing prediction, execution, exit, friction scores and counterfactual data for a single trade.
 * @param {TradeAttributionRecord} trade - Attribution record for the trade
 * @param {() => void} onClose - Callback to close the panel */
export default function TradeDetailPanel({ trade, onClose }: TradeDetailPanelProps) {
  const scores = computeDomainScores(trade)

  return (
    <div className="border-t border-default mt-2 pt-3 pb-2">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-primary">
          {trade.asset} · {trade.side.toUpperCase()} · {trade.entry_date} → {trade.exit_date}
        </h4>
        <button onClick={onClose} className="p-1 rounded hover:bg-default/40 transition-colors">
          <X className="w-3 h-3 text-tertiary" />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-2xs">
        {/* Prediction */}
        <div className="space-y-1.5">
          <p className="font-semibold text-accent-blue">Prediction</p>
          <div className="text-tertiary space-y-0.5">
            <p>Signal: <span className="text-secondary">{trade.pred_signal}</span></p>
            <p>Confidence: <span className="text-secondary">{(trade.pred_confidence * 100).toFixed(0)}%</span></p>
            <p>Direction correct: <span className={trade.pred_forecast_direction_correct ? 'text-gov-green' : 'text-gov-red'}>
              {trade.pred_forecast_direction_correct === null ? '—' : trade.pred_forecast_direction_correct ? 'Yes' : 'No'}
            </span></p>
            <p>Archetype: <span className="text-secondary">{trade.pred_archetype_at_entry}</span></p>
            <p>Regime: <span className="text-secondary">{trade.pred_regime_at_entry}</span></p>
          </div>
          <BarRow label="Score" value={scores.prediction_score} color="var(--color-accent-blue)" cssColor />
        </div>

        {/* Execution */}
        <div className="space-y-1.5">
          <p className="font-semibold text-accent-purple">Execution</p>
          <div className="text-tertiary space-y-0.5">
            <p>Type: <span className="text-secondary">{trade.exec_entry_type}</span></p>
            <p>Entry slip: <span className={trade.friction_entry_slippage_bps > 5 ? 'text-gov-red' : 'text-gov-green'}>
              {trade.friction_entry_slippage_bps.toFixed(1)} bps
            </span></p>
            <p>Exit slip: <span className={trade.friction_exit_slippage_bps > 5 ? 'text-gov-red' : 'text-gov-green'}>
              {trade.friction_exit_slippage_bps.toFixed(1)} bps
            </span></p>
            <p>Fill ratio: <span className="text-secondary">{((trade.friction_fill_qty_ratio ?? 1) * 100).toFixed(0)}%</span></p>
            <p>Latency: <span className="text-secondary">{trade.friction_latency_bars ?? '—'} bars</span></p>
            {trade.friction_gap_fill && <p className="text-gov-red">⚠ Gap fill</p>}
            {trade.friction_partial_fill && <p className="text-gov-yellow">⚠ Partial fill</p>}
          </div>
          <BarRow label="Score" value={scores.execution_score} color="var(--color-accent-purple)" cssColor />
        </div>

        {/* Exit */}
        <div className="space-y-1.5">
          <p className="font-semibold text-gov-green">Exit</p>
          <div className="text-tertiary space-y-0.5">
            <p>Reason: <span className="text-secondary">{trade.exit_exit_reason}</span></p>
            <p>Realized R: <span className={trade.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}>{trade.exit_realized_r.toFixed(2)}</span></p>
            <p>MAE: <span className="text-gov-red">{trade.exit_mae.toFixed(2)}</span></p>
            <p>MFE: <span className="text-gov-green">{trade.exit_mfe.toFixed(2)}</span></p>
            <p>Bars held: <span className="text-secondary">{trade.exit_bars_held}</span></p>
            <p>Exit archetype: <span className="text-secondary">{trade.exit_archetype}</span></p>
          </div>
          <BarRow label="Score" value={scores.exit_score} color="var(--color-gov-green)" cssColor />
        </div>

        {/* Friction */}
        <div className="space-y-1.5">
          <p className="font-semibold text-gov-yellow">Friction</p>
          <div className="text-tertiary space-y-0.5">
            <p>Entry slip: <span className="text-secondary">{trade.friction_entry_slippage_bps.toFixed(1)} bps</span></p>
            <p>Exit slip: <span className="text-secondary">{trade.friction_exit_slippage_bps.toFixed(1)} bps</span></p>
            <p>Fill qty: <span className="text-secondary">{((trade.friction_fill_qty_ratio ?? 1) * 100).toFixed(0)}%</span></p>
            <p>Latency: <span className="text-secondary">{trade.friction_latency_bars ?? '—'} bars</span></p>
            <p>Gap fill: <span className={trade.friction_gap_fill ? 'text-gov-red' : 'text-gov-green'}>{trade.friction_gap_fill ? 'Yes' : 'No'}</span></p>
            <p>Partial: <span className={trade.friction_partial_fill ? 'text-gov-yellow' : 'text-gov-green'}>{trade.friction_partial_fill ? 'Yes' : 'No'}</span></p>
          </div>
          <BarRow label="Score" value={scores.friction_score} color="var(--color-accent-amber)" cssColor />
        </div>
      </div>

      {/* Counterfactual comparison */}
      <div className="mt-3 pt-2 border-t border-default/40 text-2xs">
        <p className="font-semibold text-tertiary mb-1">Counterfactual</p>
        <div className="grid grid-cols-3 gap-2 text-tertiary">
          <div>Timing R: <span className="text-secondary">{trade.exec_counterfactual_entry_timing_r?.toFixed(2) ?? '—'}</span></div>
          <div>Ideal fill R: <span className="text-secondary">{trade.friction_counterfactual_ideal_fill_r?.toFixed(2) ?? '—'}</span></div>
          <div>Real fill R: <span className="text-secondary">{trade.friction_counterfactual_real_fill_r?.toFixed(2) ?? '—'}</span></div>
        </div>
      </div>
    </div>
  )
}
