import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface MetricRowProps {
  label: string
  value: string
  valueClass?: string
}

/** Label-value row used across detail panel tabs — label on the left, value on the right with optional colour class. @param {{ label: string, value: string, valueClass?: string }} props */
export function MetricRow({ label, value, valueClass }: MetricRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-tertiary">{label}</span>
      <span className={`text-xs font-mono text-primary font-medium ${valueClass ?? ''}`}>{value}</span>
    </div>
  )
}

/** Section wrapper with title header, borders, and content area. @param {{ title: string, children: ReactNode }} props */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-t border-default pt-3 mt-3 first:border-t-0 first:pt-0 first:mt-0">
      <h4 className="text-xs font-semibold text-secondary mb-2">{title}</h4>
      {children}
    </div>
  )
}

/** Section that can be toggled open/closed by the user. @param {{ title: string, defaultOpen?: boolean, children: ReactNode }} props */
export function CollapsibleSection({ title, defaultOpen, children }: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  return (
    <div className="border-t border-default pt-3 mt-3 first:border-t-0 first:pt-0 first:mt-0">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1 text-xs font-semibold text-secondary mb-2 w-full text-left">
        {open ? <ChevronDown className="w-3 h-3" strokeWidth={2} /> : <ChevronRight className="w-3 h-3" strokeWidth={2} />}
        {title}
      </button>
      {open && <div className="space-y-1">{children}</div>}
    </div>
  )
}
