import { useState, useRef, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

interface TablePaginationProps {
  page: number
  hasMore: boolean
  totalItems?: number
  totalPages?: number
  onPrev: () => void
  onNext: () => void
  onPageJump?: (page: number) => void
  className?: string
}

/** Bottom-of-table pagination with prev/next buttons, page jump input, and page counter. @param page - zero-indexed page number; @param hasMore - whether a next page exists; @param totalPages - total number of pages (optional, enables page-jump). */
export default function TablePagination({
  page, hasMore, totalItems, totalPages, onPrev, onNext, onPageJump, className = '',
}: TablePaginationProps) {
  const [jumpOpen, setJumpOpen] = useState(false)
  const [jumpValue, setJumpValue] = useState('')
  const jumpRef = useRef<HTMLDivElement>(null)

  const handleJump = useCallback(() => {
    const n = parseInt(jumpValue, 10)
    if (!isNaN(n) && n >= 1 && (!totalPages || n <= totalPages)) {
      onPageJump?.(n - 1) // Convert to 0-indexed
    }
    setJumpOpen(false)
    setJumpValue('')
  }, [jumpValue, totalPages, onPageJump])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (jumpRef.current && !jumpRef.current.contains(e.target as Node)) {
        setJumpOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {totalPages != null && totalPages > 1 && (
        <button
          type="button"
          onClick={() => onPageJump?.(0)}
          disabled={page === 0}
          className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
          aria-label="First page"
        >
          <ChevronsLeft className="w-3 h-3 text-secondary" strokeWidth={2} />
        </button>
      )}
      <button
        type="button"
        onClick={onPrev}
        disabled={page === 0}
        className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
        aria-label="Previous page"
      >
        <ChevronLeft className="w-3 h-3 text-secondary" strokeWidth={2} />
      </button>

      {/* Page counter — clickable to jump */}
      <div className="relative" ref={jumpRef}>
        <button
          type="button"
          onClick={() => setJumpOpen(true)}
          className="text-2xs text-tertiary font-mono tabular-nums hover:text-secondary transition-colors px-1"
          title="Click to jump to page"
        >
          Page {page + 1}{hasMore ? '+' : ''}
          {totalItems != null ? ` · ${totalItems}` : ''}
        </button>
        {jumpOpen && (
          <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 z-10 bg-surface border border-default rounded shadow-card p-1.5 flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={totalPages ?? 999}
              value={jumpValue}
              onChange={e => setJumpValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleJump(); if (e.key === 'Escape') setJumpOpen(false) }}
              className="w-14 text-2xs bg-panel border border-default rounded px-1 py-0.5 text-primary font-mono text-center outline-none focus:border-strong"
              placeholder={`${page + 1}`}
              autoFocus
            />
            <button
              type="button"
              onClick={handleJump}
              className="text-2xs font-medium text-accent-emerald hover:text-accent-emerald/80 px-1"
            >
              Go
            </button>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onNext}
        disabled={!hasMore}
        className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
        aria-label="Next page"
      >
        <ChevronRight className="w-3 h-3 text-secondary" strokeWidth={2} />
      </button>
      {totalPages != null && totalPages > 1 && (
        <button
          type="button"
          onClick={() => onPageJump?.(totalPages - 1)}
          disabled={page >= totalPages - 1}
          className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
          aria-label="Last page"
        >
          <ChevronsRight className="w-3 h-3 text-secondary" strokeWidth={2} />
        </button>
      )}
    </div>
  )
}
