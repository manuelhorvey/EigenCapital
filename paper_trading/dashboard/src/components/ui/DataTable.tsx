import { useState, useMemo, type ReactNode } from 'react'
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'

export interface ColumnDef<T> {
  key: string
  label: string
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
  width?: string
  render: (row: T) => ReactNode
  sortKey?: (row: T) => number | string
}

interface DataTableProps<T> {
  columns: ColumnDef<T>[]
  data: T[]
  keyExtractor: (row: T) => string
  sortable?: boolean
  defaultSortKey?: string
  defaultSortDir?: 'asc' | 'desc'
  stickyHeader?: boolean
  compact?: boolean
  emptyMessage?: string
  onRowClick?: (row: T) => void
  className?: string
  storageKey?: string
}

type SortDir = 'asc' | 'desc' | null

function loadSort(key: string): { col: string; dir: SortDir } | null {
  try {
    const v = sessionStorage.getItem(`qf_sort_${key}`)
    return v ? JSON.parse(v) : null
  } catch { return null }
}

function saveSort(key: string, col: string, dir: SortDir) {
  try { sessionStorage.setItem(`qf_sort_${key}`, JSON.stringify({ col, dir })) } catch {}
}

export default function DataTable<T>({
  columns, data, keyExtractor, sortable = false,
  defaultSortKey, defaultSortDir = 'desc',
  stickyHeader = true, compact = false, emptyMessage = 'No data',
  onRowClick, className = '', storageKey,
}: DataTableProps<T>) {
  const initial = storageKey ? loadSort(storageKey) : null
  const [sortCol, setSortCol] = useState<string | null>(initial?.col ?? defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState<SortDir>(initial?.dir ?? defaultSortDir)

  const sorted = useMemo(() => {
    if (!sortCol || !sortDir) return data
    const col = columns.find(c => c.key === sortCol)
    if (!col?.sortable) return data
    const fn = col.sortKey ?? ((r: any) => r[sortCol])
    return [...data].sort((a, b) => {
      const va = fn(a)
      const vb = fn(b)
      if (typeof va === 'number' && typeof vb === 'number') {
        return sortDir === 'asc' ? va - vb : vb - va
      }
      return sortDir === 'asc'
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va))
    })
  }, [data, sortCol, sortDir, columns])

  const toggleSort = (key: string) => {
    if (!sortable) return
    if (sortCol === key) {
      const next: SortDir = sortDir === 'asc' ? 'desc' : sortDir === 'desc' ? null : 'asc'
      setSortDir(next)
      if (next === null) setSortCol(null)
      if (storageKey && next) saveSort(storageKey, key, next)
    } else {
      setSortCol(key)
      setSortDir('desc')
      if (storageKey) saveSort(storageKey, key, 'desc')
    }
  }

  const alignClass = {
    left: 'text-left',
    right: 'text-right',
    center: 'text-center',
  }

  return (
    <div className={`overflow-x-auto -mx-1 ${className}`}>
      <table className={`w-full text-[11px] min-w-[500px] ${compact ? 'text-[10px]' : ''}`}>
        <thead>
          <tr className="border-b border-default">
            {columns.map(col => (
              <th
                key={col.key}
                className={[
                  'table-header py-2 pr-3 last:pr-0',
                  alignClass[col.align ?? 'left'],
                  sortable && col.sortable ? 'sort-header' : '',
                ].join(' ')}
                onClick={() => col.sortable && toggleSort(col.key)}
                style={col.width ? { width: col.width } : undefined}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortable && col.sortable && (
                    sortCol === col.key
                      ? (sortDir === 'asc' ? <ArrowUp className="w-2.5 h-2.5" /> : <ArrowDown className="w-2.5 h-2.5" />)
                      : <ArrowUpDown className="w-2.5 h-2.5 text-muted/40" />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-12 text-center text-tertiary text-xs">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sorted.map((row, i) => (
              <tr
                key={keyExtractor(row)}
                onClick={() => onRowClick?.(row)}
                className={[
                  'border-b border-default/40 table-row-hover',
                  onRowClick ? 'cursor-pointer' : '',
                  i % 2 === 1 ? 'bg-panel/30' : '',
                ].join(' ')}
              >
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={[
                      `${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`,
                      alignClass[col.align ?? 'left'],
                    ].join(' ')}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
