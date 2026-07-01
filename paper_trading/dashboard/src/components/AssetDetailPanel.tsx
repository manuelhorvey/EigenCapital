import { useState } from 'react'
import { X, Shield, Sliders, Activity, BarChart3, ChevronDown, ChevronRight, List } from 'lucide-react'
import type { AssetState } from '../types/portfolio'
import { governanceText } from './ui/governance'
import WalTimeline from './WalTimeline'

type TabId = 'overview' | 'governance' | 'sizing' | 'diagnostics' | 'wal'

interface Props {
  asset: AssetState
  name: string
  onClose: () => void
}

interface MetricRowProps {
  label: string
  value: string
  valueClass?: string
}

function MetricRow({ label, value, valueClass }: MetricRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-tertiary">{label}</span>
      <span className={`text-xs font-mono text-primary font-medium ${valueClass ?? ''}`}>{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-default pt-3 mt-3 first:border-t-0 first:pt-0 first:mt-0">
      <h4 className="text-xs font-semibold text-secondary mb-2">{title}</h4>
      {children}
    </div>
  )
}

function CollapsibleSection({ title, defaultOpen, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  return (
    <div className="border-t border-default pt-3 mt-3 first:border-t-0 first:pt-0 first:mt-0">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1 text-xs font-semibold text-secondary mb-2 w-full text-left">
        {open ? <ChevronDown className="w-3 h-3" strokeWidth={2} /> : <ChevronRight className="w-3 h-3" strokeWidth={2} />}
        {title}
      </button>
      {open && <div className="space-y-1">{children}</div>}
    </div>
  )
}

const TABS: { id: TabId; label: string; icon: typeof Shield }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'governance', label: 'Governance', icon: Shield },
  { id: 'sizing', label: 'Sizing', icon: Sliders },
  { id: 'diagnostics', label: 'Diagnostics', icon: Activity },
  { id: 'wal', label: 'WAL', icon: List },
]

export default function AssetDetailPanel({ asset, name, onClose }: Props) {
  const [tab, setTab] = useState<TabId>('overview')

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[420px] bg-app border-l border-default shadow-2xl flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-default">
        <div className="flex items-center gap-2">
          <span className="font-bold text-sm text-primary">{name}</span>
          {asset.sell_only && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
              asset.tripwire_active
                ? 'bg-gov-red-muted text-gov-red border-gov-red/20 animate-pulse'
                : 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/20'
            }`}>
              {asset.tripwire_active ? 'TRIPWIRE' : 'SELL-ONLY'}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded-md hover:bg-panel transition-colors"
          aria-label="Close detail panel"
        >
          <X className="w-4 h-4 text-secondary" strokeWidth={2} />
        </button>
      </div>

      <div className="flex border-b border-default">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              tab === id
                ? 'border-accent-emerald text-primary'
                : 'border-transparent text-tertiary hover:text-secondary'
            }`}
          >
            <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {tab === 'overview' && <OverviewTab asset={asset} />}
        {tab === 'governance' && <GovernanceTab asset={asset} />}
        {tab === 'sizing' && <SizingTab asset={asset} />}
        {tab === 'diagnostics' && <DiagnosticsTab asset={asset} />}
        {tab === 'wal' && <WalTimeline assetName={name} />}
      </div>
    </div>
  )
}

function OverviewTab({ asset }: { asset: AssetState }) {
  const m = asset.metrics
  const sd = m.signal_distribution
  const pos = m.position
  // Final signal falls back to current position side when pipeline returns
  // null (which happens when the asset is already in a position and no new
  // entry is attempted).  This prevents the dashboard from displaying FLAT
  // for assets that are actively holding a position.
  const finalSignal = asset.final_signal ?? (pos?.side === 'long' ? 'BUY' : pos?.side === 'short' ? 'SELL' : 'FLAT')
  return (
    <>
      <MetricRow label="Final Signal" value={finalSignal} valueClass={finalSignal === 'BUY' ? governanceText.GREEN : finalSignal === 'SELL' ? governanceText.RED : ''} />
      <MetricRow label="Raw Signal" value={asset.last_signal?.signal ?? 'FLAT'} />
      <MetricRow label="Confidence" value={m.mean_confidence?.toFixed(1) ?? '—'} />
      <MetricRow label="Current Price" value={m.current_price?.toFixed(4) ?? '—'} />
      <MetricRow label="Validity State" value={asset.validity_state} />
      <MetricRow label="Execution State" value={asset.execution_state} />
      {asset.signal_flip && <div className="text-xs text-gov-yellow font-medium">⚠ Signal flip detected</div>}

      <Section title="Performance">
        <MetricRow label="Total Return" value={m.total_return != null ? `${m.total_return.toFixed(2)}%` : '—'} valueClass={m.total_return != null && m.total_return >= 0 ? governanceText.GREEN : governanceText.RED} />
        <MetricRow label="Drawdown" value={m.drawdown != null ? `${m.drawdown.toFixed(2)}%` : '—'} />
        <MetricRow label="MTM Return" value={m.mtm_return != null ? `${m.mtm_return.toFixed(2)}%` : '—'} />
        <MetricRow label="Profit Factor" value={m.profit_factor?.toFixed(2) ?? '—'} />
        <MetricRow label="Win Rate" value={m.win_rate != null ? `${(m.win_rate * 100).toFixed(0)}%` : '—'} />
        <MetricRow label="Sharpe" value={m.sharpe_ratio?.toFixed(2) ?? '—'} />
        <MetricRow label="Trades" value={String(m.n_trades ?? 0)} />
        <MetricRow label="Signals" value={String(m.n_signals ?? 0)} />
        {sd && <MetricRow label="Signal Dist" value={`B:${sd.BUY ?? 0} S:${sd.SELL ?? 0} F:${sd.FLAT ?? 0}`} />}
        {m.exit_reasons && (
          <MetricRow label="Exit (TP/SL/BE/Flip/Exp)" value={`${(m.exit_reasons.tp_rate * 100).toFixed(0)}/${(m.exit_reasons.sl_rate * 100).toFixed(0)}/${(m.exit_reasons.breakeven_rate * 100).toFixed(0)}/${(m.exit_reasons.flip_rate * 100).toFixed(0)}/${(m.exit_reasons.expiry_rate * 100).toFixed(0)}%`} />
        )}
      </Section>

      {pos && (
        <Section title="Position">
          <MetricRow label="Side" value={pos.side.toUpperCase()} valueClass={pos.side === 'long' ? governanceText.GREEN : governanceText.RED} />
          <MetricRow label="Entry" value={pos.entry?.toFixed(4) ?? '—'} />
          <MetricRow label="SL" value={pos.sl?.toFixed(4) ?? '—'} />
          <MetricRow label="TP" value={pos.tp?.toFixed(4) ?? '—'} />
          <MetricRow label="Unrealized PnL" value={pos.unrealized_pnl != null ? `${pos.unrealized_pnl.toFixed(2)}%` : '—'} valueClass={pos.unrealized_pnl != null && pos.unrealized_pnl >= 0 ? governanceText.GREEN : governanceText.RED} />
          <MetricRow label="Volume" value={pos.current_vol?.toFixed(2) ?? '—'} />
        </Section>
      )}
    </>
  )
}

function GovernanceTab({ asset }: { asset: AssetState }) {
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
        <MetricRow label="Halted" value={h.halted ? 'Yes' : 'No'} valueClass={h.halted ? governanceText.RED : governanceText.GREEN} />
        <MetricRow label="Drawdown OK" value={h.drawdown_ok ? 'Yes' : 'No'} />
        <MetricRow label="Monthly PF OK" value={h.monthly_pf_ok ? 'Yes' : 'No'} />
        <MetricRow label="Drought OK" value={h.drought_ok ? 'Yes' : 'No'} />
        <MetricRow label="Drift OK" value={h.drift_ok ? 'Yes' : 'No'} />
        <MetricRow label="Narrative OK" value={h.narrative_ok ? 'Yes' : 'No'} />
        <MetricRow label="Liquidity OK" value={h.liquidity_ok ? 'Yes' : 'No'} />
        <MetricRow label="PSI OK" value={h.psi_ok ? 'Yes' : 'No'} />
        {h.halted && (
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

function SizingTab({ asset }: { asset: AssetState }) {
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
            <MetricRow key={k} label={k} value={`SL=${v.sl_mult?.toFixed(2)}x TP=${v.tp_mult?.toFixed(2)}x`} />
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

function DiagnosticsTab({ asset }: { asset: AssetState }) {
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
