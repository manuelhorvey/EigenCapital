import type { AssetState } from '../../types/portfolio'
import { governanceText } from '../ui/governance'
import { MetricRow, Section, CollapsibleSection } from './helpers'

interface Props {
  asset: AssetState
}

export default function GovernanceTab({ asset }: Props) {
  const m = asset.metrics
  const h = asset.halt
  const psi = m.psi_drift

  return (
    <>
      <div className="flex items-center justify-between py-1.5">
        <span className="text-xs text-tertiary">Validity</span>
        <div className="flex items-center gap-2">
          <div className="w-16 h-1.5 bg-panel rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${((asset.validity_exposure ?? 0) * 100).toFixed(0)}%`,
                backgroundColor: (asset.validity_exposure ?? 0) >= 0.7 ? 'var(--color-gov-green, #22c55e)' : (asset.validity_exposure ?? 0) >= 0.4 ? 'var(--color-gov-yellow, #eab308)' : 'var(--color-gov-red, #ef4444)',
              }}
            />
          </div>
          <span className="text-xs font-mono text-primary font-medium">{(asset.validity_exposure ?? 0).toFixed(2)}</span>
        </div>
      </div>
      <MetricRow label="SL Mult (effective)" value={m.current_sl_mult?.toFixed(4) ?? '—'} />
      <MetricRow label="TP Mult (effective)" value={m.current_tp_mult?.toFixed(4) ?? '—'} />
      <MetricRow label="Gate Override" value={asset.gate_override ? 'Yes' : 'No'} />

      <Section title="Regime">
        <MetricRow label="Narrative Regime" value={asset.narrative_regime ?? '—'} />
        <MetricRow label="Narrative Stale" value={asset.narrative_stale ? 'Yes' : 'No'} />
        <MetricRow label="Liquidity Regime" value={asset.liquidity_regime} />
        <MetricRow label="SL Mult (narrative)" value={asset.narrative_sl_mult?.toFixed(4) ?? '—'} />
        <MetricRow label="SL Mult (liquidity)" value={asset.liquidity_sl_mult?.toFixed(4) ?? '—'} />
      </Section>

      <Section title="Halt Checks">
        <MetricRow label="Halted" value={h?.halted ? 'Yes' : 'No'} valueClass={h?.halted ? governanceText.RED : governanceText.GREEN} />
        <MetricRow label="Drawdown OK" value={h?.drawdown_ok ? 'Yes' : 'No'} />
        <MetricRow label="Monthly PF OK" value={h?.monthly_pf_ok ? 'Yes' : 'No'} />
        <MetricRow label="Drought OK" value={h?.drought_ok ? 'Yes' : 'No'} />
        <MetricRow label="Drift OK" value={h?.drift_ok ? 'Yes' : 'No'} />
        <MetricRow label="Narrative OK" value={h?.narrative_ok ? 'Yes' : 'No'} />
        <MetricRow label="Liquidity OK" value={h?.liquidity_ok ? 'Yes' : 'No'} />
        <MetricRow label="PSI OK" value={h?.psi_ok ? 'Yes' : 'No'} />
        {h?.halted && (
          <div className="text-xs text-gov-red font-medium mt-1">⛔ {h.reasons.join('; ')}</div>
        )}
      </Section>

      {psi && (
        <Section title="PSI Drift">
          <MetricRow label="Worst" value={psi.worst_classification} valueClass={psi.worst_classification === 'severe' ? governanceText.RED : psi.worst_classification === 'moderate' ? governanceText.YELLOW : ''} />
          <MetricRow label="Moderate" value={String(psi.moderate_count)} />
          <MetricRow label="Severe" value={String(psi.severe_count)} />
          {psi.per_feature && psi.per_feature.length > 0 && (
            <CollapsibleSection title={`Per-Feature (${psi.per_feature.length})`}>
              {psi.per_feature.slice(0, 10).map(f => (
                <MetricRow key={f.feature} label={f.feature} value={`PSI=${f.psi.toFixed(4)} ${f.classification}`} />
              ))}
            </CollapsibleSection>
          )}
        </Section>
      )}

      {m.meta_inference && (
        <Section title="Meta-Labeling">
          <MetricRow label="Meta Confidence" value={m.meta_inference.meta_confidence?.toFixed(4) ?? '—'} />
          <MetricRow label="Meta Decision" value={m.meta_inference.meta_decision ?? '—'} valueClass={m.meta_inference.meta_decision === 'BLOCK' ? governanceText.RED : governanceText.GREEN} />
        </Section>
      )}

      {asset.soft_warnings?.length > 0 && (
        <div className="text-xs text-gov-yellow font-medium">⚠ Warnings: {asset.soft_warnings.join(', ')}</div>
      )}
    </>
  )
}
