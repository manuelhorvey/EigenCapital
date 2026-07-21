import { useState, useRef, useCallback, useMemo, useEffect, type ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown, Eye } from 'lucide-react'
import { useTableSort } from '../../hooks/useTableSort'
import MobileCardList from './MobileCardList'
import { Skeleton } from './Skeleton'

export interface ColumnDef<T> {
  key: string
  label: string
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
  width?: string
  minWidth?: string
  render: (row: T) => ReactNode
  sortKey?: (row: T) => number | string
  /** If true, this column is hidden by default in column visibility toggle */
  hidden?: boolean
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
  virtualize?: boolean
  rowHeight?: number
  maxHeight?: number
  /** Show loading skeleton rows when data is being fetched */
  loading?: boolean
  /** Number of skeleton rows to show */
  loadingRows?: number
  /** Enable column visibility toggle (Eye button in header).
   *  Note: when both `virtualize` and `showColumnToggle` are true,
   *  virtualization is disabled — the column toggle uses <th> elements
   *  which aren't compatible with the flex-based virtualized layout. */
  showColumnToggle?: boolean
}

const alignClass = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
}

function getColFlex<T>(col: ColumnDef<T>) {
  return col.width ? { flex: 'none', width: col.width } : { flex: 1 }
}

function DesktopEmpty({ message }: { message: string }) {
  return (
    <div className="hidden sm:block py-12 text-center text-tertiary text-xs">{message}</div>
  )
}

function MobileEmpty({ message }: { message: string }) {
  return (
    <div className="sm:hidden py-10 text-center text-tertiary text-xs border border-default rounded-lg bg-panel/40">
      {message}
    </div>
  )
}

export default function DataTable<T>({
  columns, data, keyExtractor, sortable = false,
  defaultSortKey, defaultSortDir = 'desc',
  stickyHeader = true, compact = false, emptyMessage = 'No data',
  onRowClick, className = '', storageKey, onSortChange, mobileAccent, rowClassName,
  virtualize = false, rowHeight = 48, maxHeight = 640,
  loading = false, loadingRows = 5, showColumnToggle = false,
}: DataTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrolled, setScrolled] = useState(false)
  const [colVisibility, setColVisibility] = useState<Record<string, boolean>>(() => {
    // Initialize visibility: hidden columns start hidden
    const init: Record<string, boolean> = {}
    for (const col of columns) {
      init[col.key] = !col.hidden
    }
    return init
  })
  const [colMenuOpen, setColMenuOpen] = useState(false)
  const colMenuRef = useRef<HTMLDivElement>(null)

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (el) setScrolled(el.scrollTop > 0)
  }, [])

  const { sortCol, sortDir, sortedData, toggleSort, sortAria } = useTableSort(data, columns, {
    sortable,
    defaultSortKey,
    defaultSortDir,
    storageKey,
    onSortChange,
  })

  // Visible columns (filtered by column visibility)
  const visibleColumns = useMemo(() =>
    columns.filter(col => colVisibility[col.key] !== false),
  [columns, colVisibility])

  // Close column menu on outside click
  useEffect(() => {
    if (!colMenuOpen) return
    const handler = (e: MouseEvent) => {
      if (colMenuRef.current && !colMenuRef.current.contains(e.target as Node)) {
        setColMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [colMenuOpen])

  const isEmpty = sortedData.length === 0 && !loading

  // ── Render header cells ───────────────────────
  const renderHeaderCells = () =>
    visibleColumns.map(col => (
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
        style={{ width: col.width, minWidth: col.minWidth }}
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
    ))

  // ── Render virtualized scrollable rows ────────
  const renderVirtualized = () => (
    <div className="hidden sm:block overflow-hidden" style={{ height: maxHeight }}>
      <div className={`sticky top-0 bg-app z-10 flex items-center transition-shadow duration-200 ${scrolled ? 'shadow-[0_2px_8px_rgba(0,0,0,0.25)]' : ''}`}>
        {renderHeaderCells()}
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-y-auto"
        style={{ height: maxHeight, overflowX: 'auto' }}
      >
        <div className={className} style={{ minWidth: 500 }}>
          <div className="w-full text-[11px]">
            {loading ? (
              Array.from({ length: loadingRows }).map((_, i) => (
                <div key={`skel-${i}`} style={{ height: rowHeight }} className="flex items-center border-b border-default/30 px-0">
                  {visibleColumns.map(col => (
                    <div key={col.key} className={`py-1 pr-3 last:pr-0`} style={{ minWidth: col.minWidth, ...getColFlex(col) }}>
                      <Skeleton className="h-3 rounded w-full" shimmer />
                    </div>
                  ))}
                </div>
              ))
            ) : (
              sortedData.map((row, index) => (
                <div
                  key={keyExtractor(row)}
                  role="row"
                  onClick={() => onRowClick?.(row)}
                  style={{ height: rowHeight }}
                  className={[
                    'flex items-center border-b border-default/30 table-row-hover',
                    onRowClick ? 'cursor-pointer' : '',
                    index % 2 === 1 ? 'bg-panel/30' : '',
                    rowClassName?.(row) ?? '',
                  ].join(' ')}
                >
                  {visibleColumns.map(col => (
                    <div
                      key={col.key}
                      role="cell"
                      className={[`${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`, alignClass[col.align ?? 'left']].join(' ')}
                      style={{ minWidth: col.minWidth, ...getColFlex(col) }}
                    >
                      {col.render(row)}
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )

  // ── Render table (non-virtualized) ────────────
  const renderTable = () => (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className={`hidden sm:block overflow-auto -mx-1 ${className}`}
    >
      <table className={`w-full text-[11px] min-w-[500px] ${compact ? 'text-[10px]' : ''}`}>
      <thead>
        <tr
          className={`transition-shadow duration-200 ${
            scrolled && stickyHeader ? 'shadow-[0_2px_8px_rgba(0,0,0,0.25)]' : ''
          }`}
        >
          {renderHeaderCells()}
          {showColumnToggle && (
            <th className="sticky right-0 bg-app z-20 w-8 min-w-[32px]" scope="col">
              <div className="relative" ref={colMenuRef}>
                <button
                  type="button"
                  onClick={() => setColMenuOpen(prev => !prev)}
                  className="p-1 rounded hover:bg-panel transition-colors text-tertiary hover:text-secondary"
                  aria-label="Toggle column visibility"
                  title="Columns"
                >
                  <Eye className="w-3.5 h-3.5" strokeWidth={1.5} />
                </button>
                {colMenuOpen && (
                  <div className="absolute right-0 top-full mt-1 z-50 bg-surface border border-default rounded-lg shadow-card p-1.5 min-w-[160px]">
                    <div className="text-2xs font-medium text-tertiary uppercase tracking-wider px-2 py-1">
                      Show columns
                    </div>
                    {columns.map(col => (
                      <label
                        key={col.key}
                        className="flex items-center gap-2 px-2 py-1 rounded hover:bg-panel cursor-pointer text-xs text-secondary"
                      >
                        <input
                          type="checkbox"
                          className="toggle"
                          checked={colVisibility[col.key] !== false}
                          onChange={() => setColVisibility(prev => ({ ...prev, [col.key]: !(prev[col.key] ?? true) }))}
                        />
                        {col.label}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {loading ? (
          Array.from({ length: loadingRows }).map((_, i) => (
            <tr key={`skel-${i}`} className="border-b border-default/30">
              {visibleColumns.map(col => (
                <td key={col.key} className={`${compact ? 'py-1.5' : 'py-1'} pr-3 last:pr-0`} style={{ minWidth: col.minWidth }}>
                  <Skeleton className="h-3 rounded w-full" shimmer />
                </td>
              ))}
            </tr>
          ))
        ) : (
          sortedData.map((row, i) => (
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
              {visibleColumns.map(col => (
                <td key={col.key} className={[`${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`, alignClass[col.align ?? 'left']].join(' ')} style={{ minWidth: col.minWidth }}>
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

  return (
    <>
      {isEmpty && !loading ? <MobileEmpty message={emptyMessage} /> : (
        <div className="sm:hidden">
          <MobileCardList
            items={sortedData.map(row => ({
              id: keyExtractor(row),
              onClick: onRowClick ? () => onRowClick(row) : undefined,
              accent: mobileAccent?.(row),
              content: (
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
                  {visibleColumns.map(col => (
                    <div key={col.key} className={col.align === 'right' ? 'text-right' : ''}>
                      <dt className="text-[10px] font-semibold uppercase tracking-wider text-tertiary truncate">{col.label}</dt>
                      <dd className="text-xs text-primary mt-0.5 min-w-0 overflow-hidden">{col.render(row)}</dd>
                    </div>
                  ))}
                </dl>
              ),
            }))}
          />
        </div>
      )}

      {isEmpty && !loading ? <DesktopEmpty message={emptyMessage} /> : (
        virtualize && !showColumnToggle ? renderVirtualized() : renderTable()
      )}
    </>
  )
}
