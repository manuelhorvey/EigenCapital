import { useState, useRef, useCallback, type ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { useTableSort } from '../../hooks/useTableSort'
import MobileCardList from './MobileCardList'

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
  virtualize?: boolean
  rowHeight?: number
  maxHeight?: number
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
}: DataTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrolled, setScrolled] = useState(false)

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

  const isEmpty = sortedData.length === 0

  return (
    <>
      {isEmpty ? (
        <MobileEmpty message={emptyMessage} />
      ) : (
        <div className="sm:hidden">
          <MobileCardList
            items={sortedData.map(row => ({
              id: keyExtractor(row),
              onClick: onRowClick ? () => onRowClick(row) : undefined,
              accent: mobileAccent?.(row),
              content: (
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
              ),
            }))}
          />
        </div>
      )}

      {isEmpty ? (
        <DesktopEmpty message={emptyMessage} />
      ) : virtualize ? (
        <div className="hidden sm:block overflow-hidden -mx-1" style={{ height: maxHeight }}>
          <div className="sticky top-0 bg-app z-10 flex items-center transition-shadow duration-200">
            {columns.map(col => (
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
                ].join(' ')}
                onClick={() => col.sortable && toggleSort(col.key)}
                onKeyDown={event => {
                  if (!col.sortable) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    toggleSort(col.key)
                  }
                }}
                style={{ minWidth: col.minWidth, ...getColFlex(col) }}
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
            ))}
          </div>
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className={`overflow-y-auto ${scrolled ? 'shadow-[0_2px_8px_rgba(0,0,0,0.25)]' : ''}`}
            style={{ height: maxHeight, overflowX: 'auto' }}
          >
            <div className={className} style={{ minWidth: 500 }}>
              <div className="w-full text-[11px]">
                {sortedData.map((row, index) => (
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
                    {columns.map(col => (
                      <div
                        key={col.key}
                        role="cell"
                        className={[
                          `${compact ? 'py-1.5' : 'py-2'} pr-3 last:pr-0`,
                          alignClass[col.align ?? 'left'],
                        ].join(' ')}
                        style={{ minWidth: col.minWidth, ...getColFlex(col) }}
                      >
                        {col.render(row)}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
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
            {sortedData.map((row, i) => (
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
                    style={{ minWidth: col.minWidth }}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      )}
    </>
  )
}
