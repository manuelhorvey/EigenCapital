import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { AlertTriangle } from 'lucide-react'

export default function EmergencyHaltBanner() {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  if (!snapshot?.emergency_halt) return null

  const reason = snapshot.halt_reason || 'unknown'
  const detail = snapshot.halt_detail || ''

  return (
    <div className="bg-gov-red/10 border-b border-gov-red/30 px-4 sm:px-7 py-2 animate-fade-in">
      <div className="max-w-[90rem] mx-auto flex items-center gap-3">
        <AlertTriangle className="w-4 h-4 text-gov-red shrink-0" strokeWidth={2} />
        <div className="min-w-0">
          <span className="text-xs font-bold text-gov-red uppercase tracking-wider">Emergency Halt</span>
          <span className="text-xs text-gov-red/80 font-mono ml-2">{reason}</span>
          {detail && <p className="text-2xs text-gov-red/60 mt-0.5 truncate">{detail}</p>}
        </div>
      </div>
    </div>
  )
}
