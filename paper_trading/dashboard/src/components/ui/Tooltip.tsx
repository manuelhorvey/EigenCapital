import { useState, useRef, type ReactNode } from 'react'

type TooltipSide = 'top' | 'bottom' | 'left' | 'right'

interface TooltipProps {
  content: ReactNode
  side?: TooltipSide
  delay?: number
  children: ReactNode
  className?: string
}

const sideStyles: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
  left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
  right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
}

const arrowStyles: Record<TooltipSide, string> = {
  top: 'top-full left-1/2 -translate-x-1/2 border-l-transparent border-r-transparent border-b-transparent border-t-default',
  bottom: 'bottom-full left-1/2 -translate-x-1/2 border-l-transparent border-r-transparent border-t-transparent border-b-default',
  left: 'left-full top-1/2 -translate-y-1/2 border-t-transparent border-b-transparent border-r-transparent border-l-default',
  right: 'right-full top-1/2 -translate-y-1/2 border-t-transparent border-b-transparent border-l-transparent border-r-default',
}

export default function Tooltip({ content, side = 'top', delay = 300, children, className = '' }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  const show = () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setVisible(true), delay)
  }

  const hide = () => {
    clearTimeout(timer.current)
    setVisible(false)
  }

  return (
    <span className={`relative inline-flex ${className}`} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {visible && (
        <span
          className={`absolute z-50 pointer-events-none whitespace-nowrap ${sideStyles[side]}`}
          role="tooltip"
        >
          <span className="block bg-default border border-strong text-primary text-2xs font-medium px-2 py-1 rounded shadow-tooltip">
            {content}
          </span>
          <span className={`absolute w-0 h-0 border-4 ${arrowStyles[side]}`} />
        </span>
      )}
    </span>
  )
}
