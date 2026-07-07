import { ChevronLeft, ChevronRight } from 'lucide-react'

interface TablePaginationProps {
  page: number
  hasMore: boolean
  totalItems?: number
  onPrev: () => void
  onNext: () => void
  className?: string
}

/** Bottom-of-table pagination with prev/next buttons and page counter. @param page - zero-indexed page number; @param hasMore - whether a next page exists. */
export default function TablePagination({
  page, hasMore, totalItems, onPrev, onNext, className = '',
}: TablePaginationProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className="text-2xs text-tertiary font-mono tabular-nums">
        Page {page + 1}{hasMore ? '+' : ''}
        {totalItems != null ? ` · ${totalItems}` : ''}
      </span>
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={onPrev}
          disabled={page === 0}
          className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
          aria-label="Previous page"
        >
          <ChevronLeft className="w-3 h-3 text-secondary" strokeWidth={2} />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!hasMore}
          className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-all active:scale-95"
          aria-label="Next page"
        >
          <ChevronRight className="w-3 h-3 text-secondary" strokeWidth={2} />
        </button>
      </div>
    </div>
  )
}
