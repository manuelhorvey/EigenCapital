import { useState, useMemo, useRef, useCallback, type ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

export interface ColumnDef<T> {
  key: string
  label: string
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
  width?: string
  minWidth?: string
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
  onSortChange?: (col: string | null, dir: 'asc' | 'desc' | null) => void
  mobileAccent?: (row: T) => string | undefined
  rowClassName?: (row: T) => string
}

type SortDir = 'asc' | 'desc' | null

function loadSort(key: string): { col: string; dir: SortDir } | null {
  try {
    const v = sessionStorage.getItem(`ec_sort_${key}`)
    return v ? JSON.parse(v) : null
  } catch { return null }
}

function saveSort(key: string, col: string, dir: SortDir) {
  try { sessionStorage.setItem(`ec_sort_${key}`, JSON.stringify({ col, dir })) } catch {}
}

/** Sortable, responsive data table with column definitions, mobile card fallback, and sticky header. Generic over row type T. */
export default function DataTable<T>({
  columns, data, keyExtractor, sortable = false,
  defaultSortKey, defaultSortDir = 'desc',
  stickyHeader = true, compact = false, emptyMessage = 'No data',
  onRowClick, className = '', storageKey, onSortChange, mobileAccent, rowClassName,
}: DataTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrolled, setScrolled] = useState(false)

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (el) setScrolled(el.scrollTop > 0)
  }, [])

  const initial = storageKey ? loadSort(storageKey) : null
  const [sortCol, setSortCol] = useState<string | null>(initial?.col ?? defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState<SortDir>(initial?.dir ?? defaultSortDir)

  const sorted = useMemo(() => {
    if (!sortCol || !sortDir) return data
    const col = columns.find(c => c.key === sortCol)
    if (!col?.sortable) return data
    const fn = col.sortKey ?? ((r: T) => r[sortCol as keyof T])
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
    const next: SortDir = sortCol === key
      ? (sortDir === 'asc' ? 'desc' : sortDir === 'desc' ? null : 'asc')
      : 'desc'
    const nextCol = next === null ? null : key
    setSortCol(nextCol)
    setSortDir(next)
    if (storageKey && next && nextCol) saveSort(storageKey, nextCol, next)
    onSortChange?.(nextCol, next)
  }

  const sortAria = (key: string) => {
    if (sortCol !== key || !sortDir) return 'none'
    return sortDir === 'asc' ? 'ascending' : 'descending'
  }

  const alignClass = {
    left: 'text-left',
    right: 'text-right',
    center: 'text-center',
  }

  return (
    <>
      <div className={`sm:hidden space-y-2 ${className}`}>
        {sorted.length === 0 ? (
          <div className="py-10 text-center text-tertiary text-xs border border-default rounded-lg bg-panel/40">
            {emptyMessage}
          </div>
        ) : (
          sorted.map(row => (
            <button
              key={keyExtractor(row)}
              type="button"
              onClick={() => onRowClick?.(row)}
              disabled={!onRowClick}
              className={[
                'w-full text-left rounded-lg border border-default bg-panel/50 px-3 py-2.5',
                onRowClick ? 'active:scale-[0.99] transition-transform' : 'disabled:opacity-100',
                mobileAccent ? 'border-l-2' : '',
              ].join(' ')}
              style={mobileAccent ? { borderLeftColor: mobileAccent(row) ?? 'var(--color-border)' } : undefined}
            >
              <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
                {columns.map(col => (
                  <div key={col.key} className={col.align === 'right' ? 'text-right' : ''}>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">
                      {col.label}
                    </dt>
                    <dd className="text-xs text-primary mt-0.5 min-w-0 overflow-hidden">
                      {col.render(row)}
                    </dd>
                  </div>
                ))}
              </dl>
            </button>
          ))
        )}
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`hidden sm:block overflow-x-auto overflow-y-auto -mx-1 ${className}`}
      >
        <table className={`w-full text-[11px] min-w-[500px] ${compact ? 'text-[10px]' : ''}`}>
        <thead>
          <tr
            className={`transition-shadow duration-200 ${
              scrolled && stickyHeader ? 'shadow-[0_2px_8px_rgba(0,0,0,0.25)]' : ''
            }`}
          >
            {columns.map(col => (
              <th
                key={col.key}
                scope="col"
                tabIndex={sortable && col.sortable ? 0 : undefined}
                role={sortable && col.sortable ? 'button' : undefined}
                aria-sort={sortable && col.sortable ? sortAria(col.key) : undefined}
                aria-label={sortable && col.sortable ? `${col.label}: activate to sort` : undefined}
                className={[
                  'table-header py-2 pr-3 last:pr-0',
                  alignClass[col.align ?? 'left'],
                  sortable && col.sortable ? 'sort-header' : '',
                  stickyHeader ? 'sticky top-0 bg-app z-10' : '',
                ].join(' ')}
                onClick={() => col.sortable && toggleSort(col.key)}
                onKeyDown={event => {
                  if (!col.sortable) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    toggleSort(col.key)
                  }
                }}
                style={{
                  width: col.width,
                  minWidth: col.minWidth,
                  ...(stickyHeader ? { backgroundAttachment: 'scroll' } : {}),
                }}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortable && col.sortable && (
                    sortCol === col.key
                      ? (sortDir === 'asc'
                          ? <ChevronUp className="w-3 h-3 text-secondary" strokeWidth={2} />
                          : <ChevronDown className="w-3 h-3 text-secondary" strokeWidth={2} />)
                      : <ChevronsUpDown className="w-3 h-3 text-muted/30" strokeWidth={1.5} />
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
                  'border-b border-default/30 table-row-hover',
                  onRowClick ? 'cursor-pointer' : '',
                  i % 2 === 1 ? 'bg-panel/30' : '',
                  rowClassName?.(row) ?? '',
                ].filter(Boolean).join(' ')}
                // contentVisibility removed: provides minimal benefit for <50 row datasets
                // and can cause layout instability in scrollable containers.
              >
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={[
                      `${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`,
                      alignClass[col.align ?? 'left'],
                    ].join(' ')}
                    style={{
                      minWidth: col.minWidth,
                    }}
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
    </>
  )
}
