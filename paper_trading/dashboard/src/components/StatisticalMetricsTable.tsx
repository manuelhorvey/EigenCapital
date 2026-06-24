import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { selectStatisticalMetrics } from '../selectors/metrics'
import DataTable, { type ColumnDef } from './ui/DataTable'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'

function valClass(val: number | null, lo: number, hi: number): string {
  if (val === null) return 'text-tertiary'
  if (val >= hi) return 'text-gov-green'
  if (val >= lo) return 'text-gov-yellow'
  return 'text-gov-red'
}

function renderVal(val: number | null, lo: number, hi: number, decimals = 4): string {
  if (val === null) return '—'
  const cls = valClass(val, lo, hi)
  return `<span class="font-mono tabular-nums ${cls}">${val.toFixed(decimals)}</span>`
}

function minTrlClass(val: number | null): string {
  if (val === null) return 'text-tertiary'
  if (val <= 100) return 'text-gov-green'
  if (val <= 300) return 'text-gov-yellow'
  return 'text-gov-red'
}

function hhiClass(val: number | null): string {
  if (val === null) return 'text-tertiary'
  if (val < 0.15) return 'text-gov-green'
  if (val < 0.3) return 'text-gov-yellow'
  return 'text-gov-red'
}

interface Row {
  asset: string
  sharpe: number | null
  psr0: number | null
  psr1: number | null
  minTrl: number | null
  crs: number | null
  hhi: number | null
}

export default function StatisticalMetricsTable() {
  const { data: bundle } = useSystemSnapshot()
  const stats = selectStatisticalMetrics(bundle)

  const rows = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([asset, m]) => ({
        asset,
        sharpe: m.sharpe_ratio ?? null,
        psr0: m.psr_gt_0 ?? null,
        psr1: m.psr_gt_1 ?? null,
        minTrl: m.min_trl ?? null,
        crs: m.crs ?? null,
        hhi: m.hhi ?? null,
      }))
  }, [stats])

  const columns: ColumnDef<Row>[] = useMemo(() => [
    {
      key: 'asset',
      label: 'Asset',
      sortable: true,
      minWidth: '80px',
      render: r => <span className="font-semibold text-primary text-xs font-mono">{r.asset}</span>,
    },
    {
      key: 'sharpe',
      label: 'Sharpe',
      align: 'right',
      sortable: true,
      sortKey: r => r.sharpe ?? 0,
      render: r => (
        <span
          className={`font-mono tabular-nums ${r.sharpe !== null ? (r.sharpe >= 0 ? 'text-gov-green' : 'text-gov-red') : 'text-tertiary'}`}
          dangerouslySetInnerHTML={{ __html: r.sharpe !== null ? r.sharpe.toFixed(2) : '—' }}
        />
      ),
    },
    {
      key: 'psr0',
      label: 'PSR(>0)',
      align: 'right',
      sortable: true,
      sortKey: r => r.psr0 ?? 0,
      render: r => (
        <span
          className={`font-mono tabular-nums ${valClass(r.psr0, 0.5, 0.95)}`}
          dangerouslySetInnerHTML={{
            __html: r.psr0 !== null
              ? r.psr0 >= 0.99995 ? '>0.9999' : r.psr0.toFixed(4)
              : '—',
          }}
        />
      ),
    },
    {
      key: 'psr1',
      label: 'PSR(>1)',
      align: 'right',
      sortable: true,
      sortKey: r => r.psr1 ?? 0,
      render: r => (
        <span
          className={`font-mono tabular-nums ${valClass(r.psr1, 0.5, 0.95)}`}
          dangerouslySetInnerHTML={{
            __html: r.psr1 !== null
              ? r.psr1 >= 0.99995 ? '>0.9999' : r.psr1.toFixed(4)
              : '—',
          }}
        />
      ),
    },
    {
      key: 'minTrl',
      label: 'MinTRL',
      align: 'right',
      sortable: true,
      sortKey: r => r.minTrl ?? 999999,
      render: r => (
        <span className={`font-mono tabular-nums ${minTrlClass(r.minTrl)}`}>
          {r.minTrl !== null ? r.minTrl.toLocaleString() : '—'}
        </span>
      ),
    },
    {
      key: 'crs',
      label: 'CRS',
      align: 'right',
      sortable: true,
      sortKey: r => r.crs ?? 0,
      render: r => (
        <span className={`font-mono tabular-nums ${valClass(r.crs, 0.5, 0.7)}`}>
          {r.crs !== null ? r.crs.toFixed(4) : '—'}
        </span>
      ),
    },
    {
      key: 'hhi',
      label: 'HHI',
      align: 'right',
      sortable: true,
      sortKey: r => r.hhi ?? 999,
      render: r => (
        <span className={`font-mono tabular-nums ${hhiClass(r.hhi)}`}>
          {r.hhi !== null ? r.hhi.toFixed(4) : '—'}
        </span>
      ),
    },
  ], [])

  if (!bundle) return <TableSkeleton rows={6} />

  if (rows.length === 0) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Statistical Metrics" accent="purple" />
        <EmptyState message="No asset metrics available yet" compact />
      </Panel>
    )
  }

  return (
    <Panel className="overflow-hidden p-3.5 sm:p-4">
      <SectionHeader
        title="Statistical Metrics"
        accent="purple"
        meta={
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-tertiary font-mono tabular-nums bg-surface/50 px-1.5 py-0.5 rounded">
              {rows.length}
            </span>
            <span className="text-[9px] text-tertiary leading-tight max-w-[200px] text-right">
              PSR/MinTRL saturate at float64 ceiling for current Sharpe magnitude
            </span>
          </div>
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        keyExtractor={r => r.asset}
        sortable
        defaultSortKey="asset"
        defaultSortDir="asc"
        storageKey="statistical-metrics"
      />
    </Panel>
  )
}
