import type { ReactNode } from 'react'

interface PanelProps {
  children: ReactNode
  className?: string
  hover?: boolean
  padding?: 'md' | 'lg' | 'none'
  accent?: 'green' | 'yellow' | 'red' | 'init' | null
}

const paddingMap = {
  md: 'p-3.5 sm:p-4',
  lg: 'p-4 sm:p-5',
  none: '',
}

export default function Panel({ children, className = '', hover = false, padding = 'md', accent = null }: PanelProps) {
  const accentClass = accent ? `panel-accent panel-accent-${accent}` : ''
  return (
    <div
      className={[
        'panel rounded-lg',
        paddingMap[padding],
        hover ? 'panel-hover' : '',
        accentClass,
        className,
      ].filter(Boolean).join(' ')}
    >
      {children}
    </div>
  )
}
