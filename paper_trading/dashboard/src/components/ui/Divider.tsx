interface DividerProps {
  className?: string
  orientation?: 'horizontal' | 'vertical'
}

/** Horizontal or vertical visual divider with role="separator". */
export default function Divider({ className = '', orientation = 'horizontal' }: DividerProps) {
  if (orientation === 'vertical') {
    return (
      <div className={`w-px self-stretch bg-default/40 shrink-0 ${className}`} role="separator" aria-orientation="vertical" />
    )
  }
  return (
    <hr className={`h-px border-0 bg-default/40 ${className}`} role="separator" />
  )
}
