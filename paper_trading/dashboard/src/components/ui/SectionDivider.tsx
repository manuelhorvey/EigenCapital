interface SectionDividerProps {
  label?: string
  className?: string
}

export default function SectionDivider({ label, className = '' }: SectionDividerProps) {
  if (!label) {
    return <hr className={`border-t border-default/50 my-2 ${className}`} />
  }
  return (
    <div className={`flex items-center gap-3 my-3 ${className}`}>
      <hr className="flex-1 border-t border-default/50" />
      <span className="text-[10px] text-tertiary font-medium uppercase tracking-wider shrink-0">{label}</span>
      <hr className="flex-1 border-t border-default/50" />
    </div>
  )
}
