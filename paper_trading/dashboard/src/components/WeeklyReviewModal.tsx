import { TrendingUp, TrendingDown, Activity, Shield, AlertTriangle, Check } from 'lucide-react'
import type { z } from 'zod'
import { WeeklyReviewSchema } from '../lib/schemas'

type WeeklyReview = z.infer<typeof WeeklyReviewSchema>
import Button from './ui/Button'
import StatCard from './ui/StatCard'
import Modal from './ui/Modal'

interface WeeklyReviewModalProps {
  open: boolean
  onClose: () => void
  data: WeeklyReview
  onAcknowledge: () => void
}

function formatPnl(v: number): string {
  const prefix = v >= 0 ? '+' : ''
  return `${prefix}${v.toFixed(2)}`
}

function pnlColor(v: number): string {
  return v > 0 ? 'var(--color-signal-long)' : v < 0 ? 'var(--color-signal-short)' : 'var(--color-text-secondary)'
}

function pctColor(v: number): string {
  return v > 0 ? 'var(--color-signal-long)' : v < 0 ? 'var(--color-signal-short)' : 'var(--color-text-secondary)'
}

function textClassToVar(cls: string): string {
  if (cls === 'text-primary') return 'var(--color-text-primary)'
  if (cls === 'text-tertiary') return 'var(--color-text-tertiary)'
  return 'var(--color-text-secondary)'
}

function DeltaArrow({ value }: { value: number }) {
  if (value === 0) return null
  const up = value > 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-2xs font-medium ${up ? 'text-signal-long' : 'text-signal-short'}`}>
      {up ? <TrendingUp className="w-2.5 h-2.5" strokeWidth={2} /> : <TrendingDown className="w-2.5 h-2.5" strokeWidth={2} />}
      {up ? '+' : ''}{value.toFixed(1)}pp
    </span>
  )
}

function SummaryGrid({ summary, vsPrior }: { summary: WeeklyReview['summary']; vsPrior: WeeklyReview['vs_prior_week'] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <StatCard label="Trades" value={String(summary.n_trades)} accent={textClassToVar(summary.n_trades > 0 ? 'text-primary' : 'text-tertiary')} variant="kpi" />
      <StatCard label="Win Rate" value={`${(summary.win_rate * 100).toFixed(0)}%`} accent={pctColor(summary.win_rate - 0.5)} variant="kpi" />
      <StatCard label="Avg R" value={summary.avg_r.toFixed(2)} accent={pnlColor(summary.avg_r)} variant="kpi" />
      <StatCard label="Profit Factor" value={summary.profit_factor !== null ? summary.profit_factor.toFixed(2) : '—'} accent={textClassToVar(summary.profit_factor !== null && summary.profit_factor >= 1 ? 'text-signal-long' : 'text-tertiary')} variant="kpi" />
      <StatCard label="Total PnL" value={formatPnl(summary.total_pnl)} accent={pnlColor(summary.total_pnl)} variant="kpi" />
      <StatCard label="TP Rate" value={`${(summary.tp_rate * 100).toFixed(0)}%`} accent={textClassToVar(summary.tp_rate > summary.sl_rate ? 'text-signal-long' : 'text-tertiary')} variant="kpi" />
      <StatCard label="SL Rate" value={`${(summary.sl_rate * 100).toFixed(0)}%`} accent={textClassToVar(summary.sl_rate > 0.3 ? 'text-signal-short' : 'text-tertiary')} variant="kpi" />
      <StatCard label="Best R" value={summary.best_r_multiple.toFixed(2)} accent="var(--color-signal-long)" variant="kpi" />
      <StatCard label="Worst R" value={summary.worst_r_multiple.toFixed(2)} accent="var(--color-signal-short)" variant="kpi" />
      {vsPrior && (
        <div className="col-span-full flex items-center gap-3 pt-1 border-t border-default">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">vs prior week</span>
          <DeltaArrow value={vsPrior.pnl_change} />
          <DeltaArrow value={vsPrior.win_rate_change * 100} />
          <DeltaArrow value={vsPrior.tp_rate_change * 100} />
          <DeltaArrow value={vsPrior.sl_rate_change * 100} />
        </div>
      )}
    </div>
  )
}

function AssetBreakdown({ byAsset }: { byAsset: WeeklyReview['by_asset'] }) {
  if (byAsset.length === 0) return null
  return (
    <div>
      <h3 className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Per Asset</h3>
      <div className="overflow-x-auto -mx-4 px-4">
        <table className="w-full text-2xs">
          <thead>
            <tr className="text-tertiary border-b border-default">
              <th className="text-left py-1.5 pr-3 font-medium">Asset</th>
              <th className="text-right px-2 py-1.5 font-medium">n</th>
              <th className="text-right px-2 py-1.5 font-medium">W%</th>
              <th className="text-right px-2 py-1.5 font-medium">TP%</th>
              <th className="text-right px-2 py-1.5 font-medium">avg R</th>
              <th className="text-right pl-2 py-1.5 font-medium">PnL</th>
            </tr>
          </thead>
          <tbody>
            {byAsset.map(a => (
              <tr key={a.asset} className="border-b border-default/50">
                <td className="py-1.5 pr-3 text-primary font-medium">{a.asset}</td>
                <td className="py-1.5 px-2 text-right text-secondary">{a.n_trades}</td>
                <td className="py-1.5 px-2 text-right" style={{ color: pctColor(a.win_rate - 0.5) }}>{(a.win_rate * 100).toFixed(0)}%</td>
                <td className="py-1.5 px-2 text-right" style={{ color: a.tp_rate > a.sl_rate ? 'var(--color-signal-long)' : 'var(--color-text-tertiary)' }}>{(a.tp_rate * 100).toFixed(0)}%</td>
                <td className="py-1.5 px-2 text-right" style={{ color: pnlColor(a.avg_r) }}>{a.avg_r.toFixed(2)}</td>
                <td className="py-1.5 pl-2 text-right" style={{ color: pnlColor(a.pnl) }}>{formatPnl(a.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ExitBreakdown({ breakdown }: { breakdown: WeeklyReview['exit_reason_breakdown'] }) {
  const total = breakdown.TP + breakdown.SL + breakdown.FLIP + breakdown.other + breakdown.BREAKEVEN + breakdown.EXPIRY + breakdown.MANUAL
  if (total === 0) return null
  return (
    <div>
      <h3 className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Exit Reasons</h3>
      <div className="flex items-center gap-3 text-2xs flex-wrap">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-signal-long" /> TP {breakdown.TP}</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-signal-short" /> SL {breakdown.SL}</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-signal-warn" /> Flip {breakdown.FLIP}</span>
        {breakdown.BREAKEVEN > 0 && <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-tertiary/40" /> BE {breakdown.BREAKEVEN}</span>}
        {breakdown.other > 0 && <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-tertiary" /> Other {breakdown.other}</span>}
      </div>
    </div>
  )
}

function TopTrades({ trades, label, up }: { trades: Record<string, unknown>[]; label: string; up: boolean }) {
  if (trades.length === 0) return null
  return (
    <div>
      <h3 className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">{label}</h3>
      <div className="space-y-1">
        {trades.map((t, i) => {
          const asset = String(t.asset ?? '')
          const reason = String(t.reason ?? '')
          const ret = Number(t.return ?? 0)
          return (
            <div key={i} className="flex items-center justify-between bg-panel/40 rounded px-2 py-1">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-2xs font-medium text-primary truncate">{asset}</span>
                <span className="text-[10px] text-tertiary">{reason}</span>
              </div>
              <span className={`text-2xs font-mono font-medium shrink-0 ${up ? 'text-signal-long' : 'text-signal-short'}`}>
                {up ? '+' : ''}{ret.toFixed(2)}R
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RegimeCorrelation({ regimes }: { regimes: WeeklyReview['regime_correlation'] }) {
  if (regimes.length === 0) return null
  return (
    <div>
      <h3 className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Regime Correlation</h3>
      <div className="space-y-1">
        {regimes.map(r => (
          <div key={r.regime} className="flex items-center justify-between bg-panel/40 rounded px-2 py-1">
            <span className="text-2xs text-primary font-medium">{r.regime}</span>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-tertiary">{r.n_trades} trades</span>
              <span className="text-2xs font-mono" style={{ color: pctColor(r.win_rate - 0.5) }}>{(r.win_rate * 100).toFixed(0)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GovernanceSummary({ gov }: { gov: WeeklyReview['governance_summary'] }) {
  return (
    <div>
      <h3 className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Governance</h3>
      <div className="flex items-center gap-3 text-2xs">
        <span className="flex items-center gap-1">
          <Shield className="w-3 h-3 text-tertiary" strokeWidth={1.5} />
          Most common: {gov.most_common_validity}
        </span>
        {gov.halted_assets.length > 0 && (
          <span className="flex items-center gap-1 text-signal-short">
            <AlertTriangle className="w-3 h-3" strokeWidth={1.5} />
            {gov.halted_assets.length} halted
          </span>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-8 gap-2">
      <Activity className="w-8 h-8 text-tertiary/40" strokeWidth={1} />
      <p className="text-xs text-tertiary">No trades this week</p>
    </div>
  )
}

/** Weekly performance review modal with summary grid, per-asset breakdown, exit reasons, and regime correlation. */
export default function WeeklyReviewModal({ open, onClose, data, onAcknowledge }: WeeklyReviewModalProps) {
  if (!open || !data) return null

  const hasTrades = data.summary.n_trades > 0

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Weekly Review"
      description={data.week_label}
      size="lg"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            icon={<Check className="w-3.5 h-3.5" strokeWidth={2} />}
            onClick={() => {
              onAcknowledge()
              onClose()
            }}
          >
            Acknowledge
          </Button>
        </div>
      }
    >
      {!hasTrades ? (
        <EmptyState />
      ) : (
        <>
          <SummaryGrid summary={data.summary} vsPrior={data.vs_prior_week} />
          <AssetBreakdown byAsset={data.by_asset} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-3">
              <ExitBreakdown breakdown={data.exit_reason_breakdown} />
              <TopTrades trades={data.top_winners} label="Top Winners" up />
              <TopTrades trades={data.top_losers} label="Top Losers" up={false} />
            </div>
            <div className="space-y-3">
              <RegimeCorrelation regimes={data.regime_correlation} />
              <GovernanceSummary gov={data.governance_summary} />
            </div>
          </div>
        </>
      )}

      <p className="text-[10px] text-tertiary/60 text-right">Generated {data.generated_at}</p>
    </Modal>
  )
}
