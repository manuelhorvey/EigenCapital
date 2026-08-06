import type { ReactNode } from 'react'
import { ChevronRight, Home } from 'lucide-react'
import { Link } from 'react-router-dom'

export interface Crumb {
  label: string
  to?: string
}

interface PageHeaderProps {
  title: string
  description?: string
  crumbs?: Crumb[]
  /** Right-aligned live status chips + actions */
  status?: ReactNode
  actions?: ReactNode
}

export default function PageHeader({ title, description, crumbs, status, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between pb-4 border-b border-default/60">
      <div className="min-w-0">
        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-[10px] text-tertiary font-mono mb-1.5">
          <Link to="/overview" className="flex items-center gap-1 hover:text-secondary transition-colors focus-ring rounded-sm" aria-label="Overview">
            <Home className="w-3 h-3" strokeWidth={1.75} />
          </Link>
          {crumbs?.map(c => (
            <span key={c.label} className="flex items-center gap-1 min-w-0">
              <ChevronRight className="w-2.5 h-2.5 text-muted shrink-0" strokeWidth={2} />
              {c.to ? (
                <Link to={c.to} className="truncate hover:text-secondary transition-colors focus-ring rounded-sm">
                  {c.label}
                </Link>
              ) : (
                <span className="truncate text-secondary">{c.label}</span>
              )}
            </span>
          ))}
        </nav>

        <h1 className="text-lg sm:text-xl font-bold tracking-tight text-primary">{title}</h1>
        {description && <p className="text-xs text-tertiary mt-1 max-w-2xl text-pretty">{description}</p>}
      </div>

      <div className="flex items-center gap-2 shrink-0 flex-wrap">
        {status}
        {actions}
      </div>
    </div>
  )
}
