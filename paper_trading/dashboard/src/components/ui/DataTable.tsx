import { useState, useMemo, useRef, useCallback, type ReactNode, type CSSProperties } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { List } from 'react-window'

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
  /** Enable virtual scrolling for large datasets. Default false. */
  virtualize?: boolean
  /** Row height in px. Default 40. */
  rowHeight?: number
  /** Overscan row count. Default 5. */
  overscanCount?: number
  /** Max table body height in px. Default 640. */
  maxHeight?: number
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

// Maintain <tbody> semantics within FixedSizeList for proper table structure.
/** Sortable, responsive data table with column definitions, mobile card fallback, and sticky header. Generic over row type T. */
export default function DataTable<T>({
  columns, data, keyExtractor, sortable = false,
  defaultSortKey, defaultSortDir = 'desc',
  stickyHeader = true, compact = false, emptyMessage = 'No data',
  onRowClick, className = '', storageKey, onSortChange, mobileAccent, rowClassName,
  virtualize = false, rowHeight = 48, overscanCount = 10, maxHeight = 640,
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
        ref={!virtualize ? scrollRef : undefined}
        onScroll={!virtualize ? handleScroll : undefined}
        className={`hidden sm:block overflow-x-auto ${virtualize ? '' : 'overflow-y-auto'} -mx-1 ${className}`}
      >
        {virtualize && sorted.length > 0 ? (
          <div role="table" className="w-full text-[11px] min-w-[500px]">
            {/* Virtualized header — flex layout matching body column widths */}
            <div role="row" className={`flex items-center ${scrolled && stickyHeader ? 'shadow-[0_2px_8px_rgba(0,0,0,0.25)]' : ''}`}>
              {columns.map(col => {
                const colFlex = col.width ? { flex: 'none', width: col.width } : { flex: 1 }
                return (
                  <div
                    key={col.key}
                    role="columnheader"
                    tabIndex={sortable && col.sortable ? 0 : undefined}
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
                      minWidth: col.minWidth,
                      ...colFlex,
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
                  </div>
                )
              })}
            </div>
            <div style={{ height: Math.min(sorted.length * rowHeight, maxHeight), overflow: 'hidden' }}>
              <List<{}>
                rowCount={sorted.length}
                rowHeight={rowHeight}
                defaultHeight={Math.min(sorted.length * rowHeight, maxHeight)}
                overscanCount={overscanCount}
                rowProps={{}}
                style={{ height: Math.min(sorted.length * rowHeight, maxHeight) }}
                rowComponent={({ index, style }: { index: number; style: CSSProperties }) => {
                  const row = sorted[index]
                  return (
                    <div
                      role="row"
                      onClick={() => onRowClick?.(row)}
                      style={style}
                      className={[
                        'flex items-center border-b border-default/30 table-row-hover',
                        onRowClick ? 'cursor-pointer' : '',
                        index % 2 === 1 ? 'bg-panel/30' : '',
                        rowClassName?.(row) ?? '',
                      ].join(' ')}
                    >
                      {columns.map(col => {
                        const colFlex = col.width ? { flex: 'none', width: col.width } : { flex: 1 }
                        return (
                          <div
                            key={col.key}
                            role="cell"
                            className={[
                              `${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`,
                              alignClass[col.align ?? 'left'],
                            ].join(' ')}
                            style={{
                              minWidth: col.minWidth,
                              ...colFlex,
                            }}
                          >
                            {col.render(row)}
                          </div>
                        )
                      })}
                    </div>
                  )
                }}
              />
            </div>
          </div>
        ) : (
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
        )}
      </div>
    </>
  )
}
