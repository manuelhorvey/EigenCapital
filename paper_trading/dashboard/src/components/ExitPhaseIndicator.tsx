import Badge from './ui/Badge'
import type { ExitPhase } from '../lib/trading-state/types'

interface ExitPhaseIndicatorProps {
  phase: ExitPhase
  slIsDynamic: boolean
  peakMfeR: number | null
}

const phaseConfig: Record<ExitPhase, { variant: 'success' | 'warning' | 'error' | 'neutral'; label: string }> = {
  BREAKEVEN: { variant: 'warning', label: 'Profit locked' },
  TRAILING: { variant: 'success', label: 'Trailing active' },
  DECAY: { variant: 'warning', label: 'Time decay' },
  STATIC: { variant: 'neutral', label: 'Static SL' },
}

export default function ExitPhaseIndicator({ phase, slIsDynamic, peakMfeR }: ExitPhaseIndicatorProps) {
  const cfg = phaseConfig[phase]
  return (
    <div className="flex items-center gap-2">
      <Badge variant={cfg.variant} dot={phase !== 'STATIC'} glow={phase === 'TRAILING'}>
        {cfg.label}
      </Badge>
      {slIsDynamic && (
        <span className="text-[10px] text-tertiary font-mono tabular-nums">
          SL ✦
        </span>
      )}
      {peakMfeR != null && (
        <span className="text-[10px] text-tertiary font-mono tabular-nums">
          {peakMfeR.toFixed(2)}R
        </span>
      )}
    </div>
  )
}
