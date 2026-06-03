import type { ReactNode } from 'react'
import ErrorBoundary from '../ErrorBoundary'

interface SectionProps {
  id: string
  title?: string
  children: ReactNode
  className?: string
  errorTitle?: string
}

export default function Section({
  id, title, children, className = '', errorTitle,
}: SectionProps) {
  return (
    <ErrorBoundary title={errorTitle ?? title ?? id}>
      <section
        id={id}
        className={`anchor-nav space-y-6 sm:space-y-8${className ? ` ${className}` : ''}`}
      >
        {children}
      </section>
    </ErrorBoundary>
  )
}
