import { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Activity, BarChart3, Shield, AlertTriangle, Check } from 'lucide-react'
import { useWeeklyReview } from '../hooks/useWeeklyReview'
import type { WeeklyReview } from '../types/portfolio'
import useFocusTrap from '../hooks/useFocusTrap'
import { useToast } from './toast/Toast'
import Button from './ui/Button'
import StatCard from './ui/StatCard'

function formatPnl(v: number): string {
  const prefix = v >= 0 ? '+' : ''
  return `${prefix}${v.toFixed(2)}`
}

function pnlColor(v: number): string {
  return v > 0 ? 'text-gov-green' : v < 0 ? 'text-gov-red' : 'text-secondary'
}

function pctColor(v: number): string {
  return v > 0 ? 'text-gov-green' : v < 0 ? 'text-gov-red' : 'text-secondary'
}

function DeltaArrow({ value }: { value: number }) {
  if (value === 0) return null
  const up = value > 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-2xs font-medium ${up ? 'text-gov-green' : 'text-gov-red'}`}>
      {up ? <TrendingUp className="w-2.5 h-2.5" strokeWidth={2} /> : <TrendingDown className="w-2.5 h-2.5" strokeWidth={2} />}
      {up ? '+' : ''}{value.toFixed(1)}pp
    </span>
  )
}

function SummaryGrid({ summary, vsPrior }: { summary: WeeklyReview['summary']; vsPrior: WeeklyReview['vs_prior_week'] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <StatCard variant="kpi" label="Trades" value={String(summary.n_trades)} valueClassName={summary.n_trades > 0 ? 'text-primary' : 'text-tertiary'} />
      <StatCard variant="kpi" label="Win Rate" value={`${(summary.win_rate * 100).toFixed(0)}%`} valueClassName={pctColor(summary.win_rate - 0.5)} />
      <StatCard variant="kpi" label="Avg R" value={summary.avg_r.toFixed(2)} valueClassName={pnlColor(summary.avg_r)} />
      <StatCard variant="kpi" label="Profit Factor" value={summary.profit_factor !== null ? summary.profit_factor.toFixed(2) : '—'} valueClassName={summary.profit_factor !== null && summary.profit_factor >= 1 ? 'text-gov-green' : 'text-tertiary'} />
      <StatCard variant="kpi" label="Total PnL" value={formatPnl(summary.total_pnl)} valueClassName={pnlColor(summary.total_pnl)} />
      <StatCard variant="kpi" label="TP Rate" value={`${(summary.tp_rate * 100).toFixed(0)}%`} valueClassName={summary.tp_rate > summary.sl_rate ? 'text-gov-green' : 'text-tertiary'} />
      <StatCard variant="kpi" label="SL Rate" value={`${(summary.sl_rate * 100).toFixed(0)}%`} valueClassName={summary.sl_rate > 0.3 ? 'text-gov-red' : 'text-tertiary'} />
      <StatCard variant="kpi" label="Best R" value={summary.best_r_multiple.toFixed(2)} valueClassName="text-gov-green" />
      <StatCard variant="kpi" label="Worst R" value={summary.worst_r_multiple.toFixed(2)} valueClassName="text-gov-red" />
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
                <td className={`py-1.5 px-2 text-right ${pctColor(a.win_rate - 0.5)}`}>{(a.win_rate * 100).toFixed(0)}%</td>
                <td className={`py-1.5 px-2 text-right ${a.tp_rate > a.sl_rate ? 'text-gov-green' : 'text-tertiary'}`}>{(a.tp_rate * 100).toFixed(0)}%</td>
                <td className={`py-1.5 px-2 text-right ${pnlColor(a.avg_r)}`}>{a.avg_r.toFixed(2)}</td>
                <td className={`py-1.5 pl-2 text-right ${pnlColor(a.pnl)}`}>{formatPnl(a.pnl)}</td>
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
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gov-green" /> TP {breakdown.TP}</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gov-red" /> SL {breakdown.SL}</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gov-yellow" /> Flip {breakdown.FLIP}</span>
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
          const entry = Number(t.entry ?? 0)
          const reason = String(t.reason ?? '')
          const ret = Number(t.return ?? 0)
          return (
            <div key={i} className="flex items-center justify-between bg-panel/40 rounded px-2 py-1">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-2xs font-medium text-primary truncate">{asset}</span>
                <span className="text-[10px] text-tertiary">{reason}</span>
              </div>
              <span className={`text-2xs font-mono font-medium shrink-0 ${up ? 'text-gov-green' : 'text-gov-red'}`}>
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
              <span className={`text-2xs font-mono ${pctColor(r.win_rate - 0.5)}`}>{(r.win_rate * 100).toFixed(0)}%</span>
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
          <span className="flex items-center gap-1 text-gov-red">
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

export default function WeeklyReviewModal() {
  const { data, show, isPending, isError, acknowledge } = useWeeklyReview()
  const { toast } = useToast()
  const modalRef = useFocusTrap()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (show && data) setOpen(true)
  }, [show, data])

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open])

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [open])

  if (!open || !data) return null

  const hasTrades = data.summary.n_trades > 0

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-8 sm:pt-16 px-4">
      <div className="fixed inset-0 bg-black/60" onClick={() => setOpen(false)} aria-hidden="true" />
      <div ref={modalRef} className="relative w-full max-w-2xl bg-card border border-default rounded-xl shadow-2xl animate-fade-in max-h-[85vh] flex flex-col" role="dialog" aria-modal="true" aria-label="Weekly Review">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-primary flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-accent-emerald" strokeWidth={1.5} />
              Weekly Review
            </h2>
            <p className="text-2xs text-tertiary font-mono mt-0.5">{data.week_label}</p>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="p-1.5 rounded-md hover:bg-panel border border-transparent hover:border-default transition-colors focus-ring"
            aria-label="Close weekly review"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 overscroll-contain">
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
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-default bg-surface/50 shrink-0 rounded-b-xl">
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Close
          </Button>
          <Button
            variant="primary"
            icon={<Check className="w-3.5 h-3.5" strokeWidth={2} />}
            onClick={() => {
              acknowledge()
              setOpen(false)
              toast({
                title: 'Weekly review acknowledged',
                description: `Marked as read for ${data.week_label}`,
                variant: 'success',
              })
            }}
          >
            Acknowledge
          </Button>
        </div>
      </div>
    </div>
  )
}
