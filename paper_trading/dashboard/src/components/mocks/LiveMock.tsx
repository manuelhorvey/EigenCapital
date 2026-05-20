import { useState, useEffect, useRef } from 'react'

interface Props {
  hovered?: boolean
}

const liveAssets = [
  { name: 'XLF', signal: 'BUY', signalClass: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
  { name: 'BTC', signal: 'SELL', signalClass: 'text-red-400 bg-red-500/10 border-red-500/30' },
  { name: 'NZDJPY', signal: 'FLAT', signalClass: 'text-amber-400 bg-amber-500/10 border-amber-500/30' },
]

export default function LiveMock({ hovered }: Props) {
  const [displayReturn, setDisplayReturn] = useState(0)
  const animRef = useRef(0)
  const startTimeRef = useRef(0)

  useEffect(() => {
    if (!hovered) {
      setDisplayReturn(0)
      return
    }

    const target = 0.56
    const duration = 600
    startTimeRef.current = performance.now()

    function tick(now: number) {
      const elapsed = now - startTimeRef.current
      const progress = Math.min(elapsed / duration, 1)
      setDisplayReturn(progress * target)
      if (progress < 1) {
        animRef.current = requestAnimationFrame(tick)
      }
    }

    animRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animRef.current)
  }, [hovered])

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-[9px] text-emerald-400">LIVE</span>
      </div>

      <div className="space-y-0.5">
        <div className="flex justify-between items-baseline">
          <span className="text-[10px] text-gray-500">Portfolio Value</span>
          <span className="text-xs font-mono text-white">$100,563</span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-[10px] text-gray-500">Return</span>
          <span className="text-xs font-mono text-emerald-400">
            +{displayReturn.toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="space-y-1 pt-1 border-t border-gray-800">
        {liveAssets.map((a) => (
          <div key={a.name} className="flex items-center justify-between">
            <span className="text-[9px] text-gray-500 font-mono">{a.name}</span>
            <span className={`px-1 py-0.5 rounded text-[8px] font-semibold border ${a.signalClass}`}>
              {a.signal}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
