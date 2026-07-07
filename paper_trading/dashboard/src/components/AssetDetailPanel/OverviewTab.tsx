import type { AssetState } from '../../types/portfolio'
import { governanceText } from '../ui/governance'
import { MetricRow, Section } from './helpers'

interface Props {
  asset: AssetState
}

/** Overview metrics tab — final signal, confidence, price, performance, and current position. @param {{ asset: AssetState }} props */
export default function OverviewTab({ asset }: Props) {
  const m = asset.metrics
  const sd = m.signal_distribution
  const pos = m.position
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
