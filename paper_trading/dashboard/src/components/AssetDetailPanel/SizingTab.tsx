import type { AssetState } from '../../types/portfolio'
import { MetricRow, Section } from './helpers'

interface Props {
  asset: AssetState
}

/** Sizing configuration tab — SL/TP multipliers, regime geometry, sizing chain break-down, and scale-out tiers. @param {{ asset: AssetState }} props */
export default function SizingTab({ asset }: Props) {
  const m = asset.metrics
  const narrativeScalar = asset.narrative_size_scalar ?? 1
  const liquidityScalar = asset.liquidity_size_scalar ?? 1
  const combined = narrativeScalar * liquidityScalar
  const sc = asset.sizing_chain

  return (
    <>
      <Section title="Configuration">
        <MetricRow label="Config SL Mult" value={asset.sl_mult?.toFixed(4) ?? '—'} />
        <MetricRow label="Config TP Mult" value={asset.tp_mult?.toFixed(4) ?? '—'} />
        <MetricRow label="Sell Only" value={asset.sell_only ? 'Yes' : 'No'} />
        <MetricRow label="Tripwire Active" value={asset.tripwire_active ? 'Yes' : 'No'} />
      </Section>

      <Section title="Regime Geometry">
        {asset.regime_geometry && Object.entries(asset.regime_geometry).length > 0 ? (
          Object.entries(asset.regime_geometry).map(([k, v]) => (
            <MetricRow key={k} label={k} value={`SL=${v?.sl_mult?.toFixed(2) ?? '—'}x TP=${v?.tp_mult?.toFixed(2) ?? '—'}x`} />
          ))
        ) : (
          <MetricRow label="Active Geometry" value="None" />
        )}
      </Section>

      <Section title="Sizing Chain">
        <MetricRow label="Exposure (validity)" value={asset.validity_exposure?.toFixed(4) ?? '—'} />
        <MetricRow label="Size Scalar (narrative)" value={`${narrativeScalar.toFixed(4)}x`} />
        <MetricRow label="Size Scalar (liquidity)" value={`${liquidityScalar.toFixed(4)}x`} />
        <MetricRow label="Size Scalar (combined)" value={`${combined.toFixed(4)}x`} />
        {sc ? (
          <>
            <MetricRow label="Drawdown Taper" value={sc.drawdown_taper != null ? `${Number(sc.drawdown_taper).toFixed(4)}x` : '—'} />
            <MetricRow label="Effective Cap" value={sc.effective_cap != null ? `$${Number(sc.effective_cap).toFixed(2)}` : '—'} />
            <MetricRow label="Size Scalar (final)" value={sc.size_scalar != null ? `${Number(sc.size_scalar).toFixed(4)}x` : '—'} />
            <MetricRow label="Position Cap" value={sc.position_cap != null ? `$${Number(sc.position_cap).toFixed(2)}` : '—'} />
            <MetricRow label="Risk Cap" value={sc.risk_cap != null ? `$${Number(sc.risk_cap).toFixed(2)}` : '—'} />
            <MetricRow label="Leverage Budget" value={sc.leverage_budget != null ? `$${Number(sc.leverage_budget).toFixed(2)}` : '—'} />
            <MetricRow label="Final Notional" value={sc.final_notional != null ? `$${Number(sc.final_notional).toFixed(2)}` : '—'} />
            <MetricRow label="Quantity" value={sc.quantity != null ? Number(sc.quantity).toFixed(6) : '—'} />
            {sc.reason && <MetricRow label="Skip Reason" value={String(sc.reason)} valueClass="text-gov-yellow" />}
          </>
        ) : (
          <MetricRow label="Active Sizing" value="No entry attempted" />
        )}
      </Section>

      {m.scale_out_active && m.scale_out_tiers && (
        <Section title="Scale-Out Tiers">
          <MetricRow label="Remaining" value={m.remaining_fraction != null ? `${(m.remaining_fraction * 100).toFixed(0)}%` : '—'} />
          {m.scale_out_tiers.map((tier, i) => (
            <MetricRow key={i} label={`Tier ${i + 1} (${(tier.fraction * 100).toFixed(0)}%)`} value={tier.filled ? `Filled @ $${tier.fill_price}` : `Pending @ $${tier.price}`} />
          ))}
        </Section>
      )}
    </>
  )
}
