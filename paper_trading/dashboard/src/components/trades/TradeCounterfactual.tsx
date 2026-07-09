import type { TradeAttributionRecord } from '../../hooks/useAttributionTrades'

interface TradeCounterfactualProps {
  data: TradeAttributionRecord
}

interface ComparisonRow {
  label: string
  actual: string
  shadow: string
  delta?: string
  positive?: boolean
}

/** Table comparing actual trade outcomes against counterfactual scenarios (ideal timing, ideal fill, real fill).
 * @param {TradeAttributionRecord} data - Attribution record with counterfactual fields */
export default function TradeCounterfactual({ data }: TradeCounterfactualProps) {
  const comparisons: ComparisonRow[] = [
    {
      label: 'Entry Timing',
      actual: `${data.exec_entry_type} @ ${data.entry_price.toFixed(2)}`,
      shadow: data.exec_counterfactual_entry_timing_r != null ? `${data.exec_entry_type} (timing R: ${data.exec_counterfactual_entry_timing_r.toFixed(2)})` : '—',
    },
    {
      label: 'Ideal Fill',
      actual: `Real: ${data.exit_realized_r.toFixed(2)} R`,
      shadow: data.friction_counterfactual_ideal_fill_r != null ? `Ideal: ${data.friction_counterfactual_ideal_fill_r.toFixed(2)} R` : '—',
    },
    {
      label: 'Real Fill (counterfactual)',
      actual: `${data.exit_realized_r.toFixed(2)} R`,
      shadow: data.friction_counterfactual_real_fill_r != null ? `${data.friction_counterfactual_real_fill_r.toFixed(2)} R` : '—',
    },
    {
      label: 'MAE / MFE',
      actual: `${data.exit_mae.toFixed(1)} / ${data.exit_mfe.toFixed(1)}`,
      shadow: `${data.exit_mae_per_bar.toFixed(2)}/bar / ${data.exit_mfe_per_bar.toFixed(2)}/bar`,
    },
  ]

  const realizedImprovement = data.friction_counterfactual_ideal_fill_r != null && data.friction_counterfactual_real_fill_r != null
    ? data.friction_counterfactual_ideal_fill_r - data.friction_counterfactual_real_fill_r
    : null

  return (
    <div className="space-y-3">
      <div className="overflow-hidden border border-default rounded-lg">
        <table className="w-full text-2xs">
          <thead>
            <tr className="bg-surface border-b border-default">
              <th className="text-left py-2 px-3 font-semibold text-tertiary uppercase tracking-wider">Metric</th>
              <th className="text-right py-2 px-3 font-semibold text-tertiary uppercase tracking-wider">Actual</th>
              <th className="text-right py-2 px-3 font-semibold text-tertiary uppercase tracking-wider">Counterfactual</th>
            </tr>
          </thead>
          <tbody>
            {comparisons.map(row => (
              <tr key={row.label} className="border-b border-default/30 last:border-0">
                <td className="py-1.5 px-3 text-primary font-medium">{row.label}</td>
                <td className="py-1.5 px-3 text-right text-secondary font-mono tabular-nums">{row.actual}</td>
                <td className="py-1.5 px-3 text-right text-secondary font-mono tabular-nums">{row.shadow}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {realizedImprovement !== null && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-accent-blue/5 border border-accent-blue/20">
          <div className="flex-1">
            <p className="text-xs font-medium text-primary">Execution Improvement Potential</p>
            <p className="text-2xs text-tertiary">If ideal fill were achieved vs real conditions</p>
          </div>
          <span className={`text-sm font-bold font-mono tabular-nums ${realizedImprovement >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
            {realizedImprovement >= 0 ? '+' : ''}{realizedImprovement.toFixed(2)} R
          </span>
        </div>
      )}
    </div>
  )
}
