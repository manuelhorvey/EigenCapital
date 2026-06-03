import { useState } from 'react'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { TableSkeleton } from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import TradeDetailPanel from '../attribution/TradeDetailPanel'
import Select from '../ui/Select'
import Badge, { signalToBadge, reasonToBadge } from '../ui/Badge'

export default function TradeExecutionTable() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: trades, isPending } = useAttributionTrades(25)
  const [archetypeFilter, setArchetypeFilter] = useState('')

  const filtered = archetypeFilter
    ? (trades ?? []).filter(t => t.pred_archetype_at_entry === archetypeFilter)
    : (trades ?? [])

  if (isPending) return <TableSkeleton rows={6} />
  if (!trades || trades.length === 0) return <Panel><EmptyState message="No attribution data yet" compact /></Panel>

  const archetypes = [...new Set(trades.map(t => t.pred_archetype_at_entry))]

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Trade Execution Detail"
        accent="blue"
        meta={
          <Select
            options={archetypes.map(a => ({ value: a, label: a }))}
            value={archetypeFilter}
            onChange={setArchetypeFilter}
            placeholder="All Archetypes"
          />
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
              const selected = selectedId === `${t.trade_id ?? t.asset}_${t.exit_date}`
              const { variant: archVariant } = signalToBadge(t.pred_archetype_at_entry)
              return (
                <>
                  <tr
                    key={`${t.trade_id ?? t.asset}_${t.exit_date}`}
                    onClick={() => setSelectedId(selected ? null : `${t.trade_id ?? t.asset}_${t.exit_date}`)}
                    className={`border-b border-default/40 table-row-hover cursor-pointer ${selected ? 'bg-panel/40' : ''}`}
                  >
                    <td className="py-2 pr-2 font-medium text-primary font-mono">{t.asset}</td>
                    <td className="py-2 pr-2">
                      <Badge variant={archVariant === 'success' ? 'success' : 'neutral'}>{t.pred_archetype_at_entry}</Badge>
                    </td>
                    <td className={`text-right py-2 pr-2 font-mono tabular-nums ${t.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                      {t.exit_realized_r.toFixed(2)}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-secondary">
                      {t.friction_entry_slippage_bps.toFixed(1)}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-secondary">
                      {t.friction_exit_slippage_bps.toFixed(1)}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-secondary">
                      {t.friction_fill_qty_ratio != null ? `${(t.friction_fill_qty_ratio * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-secondary">
                      {t.friction_latency_bars ?? '—'}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-gov-red">
                      {t.exit_mae.toFixed(2)}
                    </td>
                    <td className="text-right py-2 pr-2 font-mono tabular-nums text-gov-green">
                      {t.exit_mfe.toFixed(2)}
                    </td>
                    <td className="text-right py-2 font-mono tabular-nums">
                      <Badge variant={reasonToBadge(t.exit_exit_reason)}>{t.exit_exit_reason ?? '—'}</Badge>
                    </td>
                  </tr>
                  {selected && (
                    <tr key={`detail-${t.trade_id}`}>
                      <td colSpan={10} className="p-0">
                        <TradeDetailPanel trade={t} onClose={() => setSelectedId(null)} />
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
