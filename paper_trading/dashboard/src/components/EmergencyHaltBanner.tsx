import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { AlertTriangle } from 'lucide-react'

export default function EmergencyHaltBanner() {
  const { data: bundle } = useSystemSnapshot()
  const snapshot = bundle?.snapshot
  const emergency = snapshot?.emergency_halt

  if (!emergency) return null

  return (
    <div className="bg-gov-red/10 border border-gov-red/30 rounded-lg p-4 flex items-start gap-3 animate-pulse">
      <AlertTriangle className="w-6 h-6 text-gov-red shrink-0 mt-0.5" strokeWidth={1.5} />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gov-red">Emergency Halt Active</p>
        <p className="text-xs text-gov-red/80 mt-1 font-mono">
          {snapshot.halt_reason || 'No reason provided'}
          {snapshot.halt_detail ? ` — ${snapshot.halt_detail}` : ''}
        </p>
      </div>
    </div>
  )
}
