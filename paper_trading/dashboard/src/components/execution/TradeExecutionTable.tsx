import { useCallback, useState, useRef, useMemo, type CSSProperties } from 'react'
import { List } from 'react-window'
import { useAttributionTrades } from '../../hooks/useAttributionTrades'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { TableSkeleton } from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import TradeDetailPanel from '../attribution/TradeDetailPanel'
import SearchableSelect from '../ui/SearchableSelect'
import MobileCardList from '../ui/MobileCardList'
import Badge, { signalToBadge, reasonToBadge } from '../ui/Badge'

const ROW_HEIGHT = 40
const MAX_TABLE_HEIGHT = 640

function rowKey(t: { trade_id?: string; asset: string; exit_date: string }) {
  return `${t.trade_id ?? t.asset}_${t.exit_date}`
}

/** Table listing recent closed trades with execution detail, archetype filter, and virtual-scrolled rows. Expanded detail shown as overlay. */
export default function TradeExecutionTable() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: trades, isPending } = useAttributionTrades(100)
  const [archetypeFilter, setArchetypeFilter] = useState('')
  const overlayRef = useRef<HTMLDivElement>(null)

  const toggleRow = useCallback((id: string) => {
    setSelectedId(prev => (prev === id ? null : id))
  }, [])

  const filtered = useMemo(
    () => archetypeFilter
      ? (trades ?? []).filter(t => t.pred_archetype_at_entry === archetypeFilter)
      : (trades ?? []),
    [trades, archetypeFilter],
  )

  const selectedTrade = useMemo(
    () => filtered.find(t => rowKey(t) === selectedId) ?? null,
    [filtered, selectedId],
  )

  if (isPending) return <TableSkeleton rows={6} />
  if (!trades || trades.length === 0) return <Panel><EmptyState message="No attribution data yet" compact /></Panel>

  const archetypes = [...new Set(trades.map(t => t.pred_archetype_at_entry))]

  // ── Desktop virtual-scrolled table with overlay detail panel ──
  const DesktopTable = (
    <div className="hidden sm:block">
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[720px]">
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
        </table>
      </div>
      <div className="relative overflow-hidden" style={{ height: Math.min(filtered.length * ROW_HEIGHT, MAX_TABLE_HEIGHT) }}>
        <List<{}>
          rowCount={filtered.length}
          rowHeight={ROW_HEIGHT}
          defaultHeight={Math.min(filtered.length * ROW_HEIGHT, MAX_TABLE_HEIGHT)}
          overscanCount={10}
          rowProps={{}}
          rowComponent={({ index, style }: { index: number; style: CSSProperties }) => {
            const t = filtered[index]
            const key = rowKey(t)
            const selected = selectedId === key
            const { variant: archVariant } = signalToBadge(t.pred_archetype_at_entry)
            return (
              <div
                key={key}
                onClick={() => toggleRow(key)}
                style={style}
                className={`flex items-center border-b border-default/40 table-row-hover cursor-pointer text-xs ${selected ? 'bg-panel/40' : ''}`}
              >
                <span className="w-[80px] shrink-0 py-1.5 pr-2 font-medium text-primary font-mono truncate">{t.asset}</span>
                <span className="w-[100px] shrink-0 py-1.5 pr-2">
                  <Badge variant={archVariant === 'success' ? 'success' : 'neutral'}>{t.pred_archetype_at_entry}</Badge>
                </span>
                <span className={`flex-1 text-right py-1.5 pr-2 font-mono tabular-nums ${t.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>{t.exit_realized_r.toFixed(2)}</span>
                <span className="flex-1 text-right py-1.5 pr-2 font-mono tabular-nums text-secondary">{t.friction_entry_slippage_bps.toFixed(1)}</span>
                <span className="flex-1 text-right py-1.5 pr-2 font-mono tabular-nums text-secondary">{t.friction_exit_slippage_bps.toFixed(1)}</span>
                <span className="w-[60px] shrink-0 text-right py-1.5 pr-2 font-mono tabular-nums text-secondary">
                  {t.friction_fill_qty_ratio != null ? `${(t.friction_fill_qty_ratio * 100).toFixed(0)}%` : '—'}
                </span>
                <span className="w-[48px] shrink-0 text-right py-1.5 pr-2 font-mono tabular-nums text-secondary">{t.friction_latency_bars ?? '—'}</span>
                <span className="w-[64px] shrink-0 text-right py-1.5 pr-2 font-mono tabular-nums text-gov-red">{t.exit_mae.toFixed(2)}</span>
                <span className="w-[64px] shrink-0 text-right py-1.5 pr-2 font-mono tabular-nums text-gov-green">{t.exit_mfe.toFixed(2)}</span>
                <span className="w-[64px] shrink-0 text-right py-1.5 font-mono tabular-nums pr-3">
                  <Badge variant={reasonToBadge(t.exit_exit_reason)}>{t.exit_exit_reason ?? '—'}</Badge>
                </span>
              </div>
            )
          }}
        />

        {/* Overlay detail panel for selected trade */}
        {selectedTrade && (
          <div
            ref={overlayRef}
            className="absolute inset-0 z-20 overflow-y-auto bg-app/95 backdrop-blur-sm border-b border-default/40"
          >
            <TradeDetailPanel trade={selectedTrade} onClose={() => setSelectedId(null)} />
          </div>
        )}
      </div>
    </div>
  )

  // ── Mobile card list ───────────────────────────────────────────
  const mobileCardItems = filtered.map(t => {
    const key = rowKey(t)
    const rColor = t.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'
    return {
      id: key,
      onClick: () => toggleRow(key),
      content: (
        <>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="font-semibold text-primary text-xs font-mono">{t.asset}</span>
            <Badge variant={signalToBadge(t.pred_archetype_at_entry).variant === 'success' ? 'success' : 'neutral'}>{t.pred_archetype_at_entry}</Badge>
          </div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">R</dt>
              <dd className={`text-xs font-mono tabular-nums mt-0.5 ${rColor}`}>{t.exit_realized_r.toFixed(2)}</dd>
            </div>
            <div className="text-right">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Exit</dt>
              <dd className="text-xs mt-0.5">
                <Badge variant={reasonToBadge(t.exit_exit_reason)}>{t.exit_exit_reason ?? '—'}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Slippage</dt>
              <dd className="text-xs font-mono tabular-nums mt-0.5 text-secondary">
                E:{t.friction_entry_slippage_bps.toFixed(1)} / X:{t.friction_exit_slippage_bps.toFixed(1)}
              </dd>
            </div>
            <div className="text-right">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Fill</dt>
              <dd className="text-xs font-mono tabular-nums mt-0.5 text-secondary">
                {t.friction_fill_qty_ratio != null ? `${(t.friction_fill_qty_ratio * 100).toFixed(0)}%` : '—'}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">MAE / MFE</dt>
              <dd className="text-xs font-mono tabular-nums mt-0.5">
                <span className="text-gov-red">{t.exit_mae.toFixed(2)}</span>
                <span className="text-tertiary mx-0.5">/</span>
                <span className="text-gov-green">{t.exit_mfe.toFixed(2)}</span>
              </dd>
            </div>
            <div className="text-right">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Latency</dt>
              <dd className="text-xs font-mono tabular-nums mt-0.5 text-secondary">
                {t.friction_latency_bars ?? '—'}
              </dd>
            </div>
          </dl>
        </>
      ),
    }
  })

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Trade Execution Detail"
        accent="emerald"
        meta={
          <SearchableSelect
            options={archetypes.map(a => ({ value: a, label: a }))}
            value={archetypeFilter}
            onChange={setArchetypeFilter}
            placeholder="All Archetypes"
          />
        }
      />
      <MobileCardList items={mobileCardItems} />
      {DesktopTable}

      {/* Mobile detail panel */}
      {selectedTrade && (
        <div className="sm:hidden mt-2">
          <TradeDetailPanel trade={selectedTrade} onClose={() => setSelectedId(null)} />
        </div>
      )}
    </Panel>
  )
}
