import type { z } from 'zod'
import { AssetStateSchema } from '../../lib/schemas'

type AssetState = z.infer<typeof AssetStateSchema>
import { MetricRow, Section } from './helpers'

interface DiagnosticsTabProps {
  asset: AssetState
}

/** Diagnostics tab — feature stability, regime model output, archetype stats, and statistical metrics. @param {{ asset: AssetState }} props */
export default function DiagnosticsTab({ asset }: DiagnosticsTabProps) {
  const m = asset.metrics
  const fs = m.feature_stability

  return (
    <>
      <Section title="Feature Stability">
        <MetricRow label="Jaccard Top-10" value={asset.feature_stability_jaccard?.toFixed(4) ?? '—'} />
        <MetricRow label="Spearman Rank" value={asset.feature_stability_spearman?.toFixed(4) ?? '—'} />
        {fs && (
          <>
            <MetricRow label="Penalty" value={fs.penalty?.toFixed(4) ?? '—'} />
            <MetricRow label="Window ID" value={fs.window_id ?? '—'} />
          </>
        )}
      </Section>

      <Section title="Regime Model">
        <MetricRow label="Last Regime" value={asset.last_regime_label ?? '—'} />
        <MetricRow label="Regime Long Prob" value={asset.last_regime_long_prob?.toFixed(4) ?? '—'} />
      </Section>

      <Section title="Archetype Stats">
        {m.archetype_stats && Object.entries(m.archetype_stats).length > 0 ? (
          Object.entries(m.archetype_stats).map(([k, v]) => (
            <MetricRow key={k} label={k} value={`n=${v.n} WR=${(v.win_rate * 100).toFixed(0)}% avgR=${v.avg_r.toFixed(2)}`} />
          ))
        ) : (
          <MetricRow label="Entries" value="None" />
        )}
      </Section>

      <Section title="Statistical Metrics">
        <MetricRow label="PSR(>0)" value={m.psr_gt_0?.toFixed(4) ?? '—'} />
        <MetricRow label="PSR(>1)" value={m.psr_gt_1?.toFixed(4) ?? '—'} />
        <MetricRow label="MinTRL" value={m.min_trl?.toFixed(1) ?? '—'} />
        <MetricRow label="CRS" value={m.crs?.toFixed(4) ?? '—'} />
        <MetricRow label="HHI" value={m.hhi?.toFixed(4) ?? '—'} />
      </Section>

      <Section title="Stop-Out">
        <MetricRow label="Last Side" value={asset.stop_out_last_side ?? '—'} />
        <MetricRow label="Last Cycle" value={asset.stop_out_last_cycle?.toString() ?? '—'} />
      </Section>
    </>
  )
}
