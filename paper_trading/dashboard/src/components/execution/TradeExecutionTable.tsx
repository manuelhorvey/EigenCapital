import { useState } from 'react'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { TableSkeleton } from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import TradeDetailPanel from '../attribution/TradeDetailPanel'

export default function TradeExecutionTable() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: trades, isPending } = useAttributionTrades(25)
  const [archetypeFilter, setArchetypeFilter] = useState('')

  const filtered = archetypeFilter
    ? (trades ?? []).filter(t => t.pred_archetype_at_entry === archetypeFilter)
    : (trades ?? [])

  if (isPending) return <TableSkeleton rows={6} />
  if (!trades || trades.length === 0) return <Panel><EmptyState message="No attribution data yet" compact /></Panel>

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Trade Execution Detail"
        accent="blue"
        meta={
          <select
            value={archetypeFilter}
            onChange={e => setArchetypeFilter(e.target.value)}
            className="filter-select text-2xs"
          >
            <option value="">All Archetypes</option>
            {[...new Set(trades.map(t => t.pred_archetype_at_entry))].map(a => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        }
      />
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[800px]">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2 pr-2">Asset</th>
              <th className="table-header text-left py-2 pr-2">Archetype</th>
              <th className="table-header text-right py-2 pr-2">R</th>
              <th className="table-header text-right py-2 pr-2">Slip (E)</th>
              <th className="table-header text-right py-2 pr-2">Slip (X)</th>
              <th className="table-header text-right py-2 pr-2">Fill%</th>
              <th className="table-header text-right py-2 pr-2">Latency</th>
              <th className="table-header text-right py-2 pr-2">MAE</th>
              <th className="table-header text-right py-2 pr-2">MFE</th>
              <th className="table-header text-right py-2">Exit</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(t => {
              const eis = 1 - Math.min(Math.abs(t.exec_entry_slippage_bps) / 50, 1)
              return (
                <tr
                  key={t.trade_id}
                  onClick={() => setSelectedId(selectedId === t.trade_id ? null : t.trade_id)}
                  className="border-b border-default/40 table-row-hover cursor-pointer"
                >
                  <td className="py-2 pr-2 font-mono font-medium text-primary">{t.asset}</td>
                  <td className="py-2 pr-2">
                    <span className="signal-pill signal-pill-buy text-2xs">{t.pred_archetype_at_entry}</span>
                  </td>
                  <td className={`py-2 pr-2 text-right font-mono tabular-nums ${t.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                    {t.exit_realized_r.toFixed(2)}
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-secondary">
                    {t.friction_entry_slippage_bps.toFixed(1)}
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-secondary">
                    {t.friction_exit_slippage_bps.toFixed(1)}
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-secondary">
                    {(t.friction_fill_qty_ratio != null ? t.friction_fill_qty_ratio * 100 : 100).toFixed(0)}%
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-secondary">
                    {t.friction_latency_bars ?? '—'}
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-gov-red">
                    {t.exit_mae.toFixed(2)}
                  </td>
                  <td className="py-2 pr-2 text-right font-mono tabular-nums text-gov-green">
                    {t.exit_mfe.toFixed(2)}
                  </td>
                  <td className="py-2 text-right">
                    <span className={`signal-pill ${t.exit_exit_reason === 'tp' ? 'signal-pill-buy' : t.exit_exit_reason === 'sl' ? 'signal-pill-sell' : 'signal-pill-flat'}`}>
                      {t.exit_exit_reason}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {selectedId && (
        <TradeDetailPanel
          trade={trades.find(t => t.trade_id === selectedId)!}
          onClose={() => setSelectedId(null)}
        />
      )}
    </Panel>
  )
}
