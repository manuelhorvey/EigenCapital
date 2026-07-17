import { type ReactNode } from 'react'

interface MobileCardItem {
  id: string
  content: ReactNode
  onClick?: () => void
  accent?: string
}

interface MobileCardListProps {
  items: MobileCardItem[]
  className?: string
}

/**
 * Standardized mobile card list component — replaces duplicated mobile card-rendering patterns.
 *
 * Usage:
 *   <MobileCardList
 *     items={data.map(item => ({
 *       id: item.id,
 *       content: <MyCardContent item={item} />,
 *       onClick: () => handleClick(item),
 *       accent: item.signal === 'BUY' ? 'var(--color-gov-green)' : undefined,
 *     }))}
 *   />
 *
 * Shows on mobile (< sm), hidden on desktop (sm:hidden pattern handled by consumer).
 */
export default function MobileCardList({ items, className = '' }: MobileCardListProps) {
  if (items.length === 0) return null

  return (
    <div className={`sm:hidden space-y-2 ${className}`}>
      {items.map(item => (
        <button
          key={item.id}
          type="button"
          onClick={item.onClick}
          disabled={!item.onClick}
          className={[
            'w-full text-left rounded-lg border border-default bg-panel/50 px-3 py-2.5',
            item.onClick ? 'active:scale-[0.99] transition-transform' : 'disabled:opacity-100 cursor-default',
            item.accent ? 'border-l-2' : '',
          ].join(' ')}
          style={item.accent ? { borderLeftColor: item.accent } : undefined}
        >
          {item.content}
        </button>
      ))}
    </div>
  )
}
