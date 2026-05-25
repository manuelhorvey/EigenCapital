import { Inbox, SearchSlash } from 'lucide-react'

interface EmptyStateProps {
  message: string
  hint?: string
  compact?: boolean
  filtered?: boolean
}

export default function EmptyState({ message, hint, compact, filtered }: EmptyStateProps) {
  const Icon = filtered ? SearchSlash : Inbox
  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${
        compact ? 'py-10 px-4' : 'py-16 px-6'
      }`}
    >
      <Icon
        className={`text-tertiary/40 mb-2 ${compact ? 'w-5 h-5' : 'w-7 h-7'}`}
        strokeWidth={1.25}
      />
      <p className={`text-tertiary ${compact ? 'text-xs' : 'text-sm'}`}>{message}</p>
      {hint != null && <p className="text-muted text-[10px] mt-1 max-w-xs">{hint}</p>}
    </div>
  )
}
