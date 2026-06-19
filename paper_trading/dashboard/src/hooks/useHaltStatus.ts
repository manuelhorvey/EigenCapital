import { useMemo } from 'react'
import type { EngineSnapshot } from '../types/portfolio'

export interface HaltStatus {
  maxDrawdown: number
  minMonthlyPf: number | null
  drawdownTrigger: number
  monthlyPfTrigger: number
  drawdownPass: boolean
  monthlyPfPass: boolean
  anyTriggered: boolean
}

export function useHaltStatus(state: EngineSnapshot | undefined): HaltStatus {
  return useMemo(() => {
    const hc = state?.halt_conditions
    const assets = state?.assets ?? {}
    let maxDD = 0
    let minPF = Infinity
    for (const name in assets) {
      const m = assets[name].metrics
      if (m) {
        if (m.drawdown < maxDD) maxDD = m.drawdown
        if (m.monthly_pf != null && m.monthly_pf < minPF) minPF = m.monthly_pf
      }
    }
    const ddTrigger = (hc?.drawdown ?? -0.08) * 100
    const pfTrigger = hc?.monthly_pf ?? 0.7
    const hasMonthlyPf = minPF !== Infinity
    return {
      maxDrawdown: maxDD,
      minMonthlyPf: hasMonthlyPf ? minPF : null,
      drawdownTrigger: ddTrigger,
      monthlyPfTrigger: pfTrigger,
      drawdownPass: maxDD > ddTrigger,
      monthlyPfPass: hasMonthlyPf ? minPF >= pfTrigger : true,
      anyTriggered: maxDD <= ddTrigger || (hasMonthlyPf && minPF < pfTrigger),
    }
  }, [state])
}
