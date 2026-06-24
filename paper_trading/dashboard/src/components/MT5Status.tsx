import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { Wifi, WifiOff, AlertTriangle, Loader2 } from 'lucide-react'

export default function MT5Status() {
  const { data: bundle, isPending, isError } = useSystemSnapshot()
  const data = bundle?.live?.mt5

  const connected = data?.status === 'CONNECTED'
  const status = data?.status ?? 'UNKNOWN'
  const account = data?.account
  const equity = account?.portfolio_value != null ? Number(account.portfolio_value) : null
  const positions = account?.positions != null ? (account.positions as unknown[]).length : null

  if (isPending) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-default/50 text-2xs text-tertiary">
        <Loader2 className="w-2.5 h-2.5 animate-spin" strokeWidth={2} />
        MT5…
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-gov-red/30 bg-gov-red-muted/30 text-2xs text-gov-red">
        <AlertTriangle className="w-2.5 h-2.5" strokeWidth={2} />
        MT5 Error
      </div>
    )
  }

  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-2xs font-medium ${
        connected
          ? 'border-gov-green/30 bg-gov-green-muted/20 text-gov-green'
          : 'border-gov-yellow/30 bg-gov-yellow-muted/20 text-gov-yellow'
      }`}
      title={`MT5: ${status}${equity != null ? ` | Equity: $${equity.toLocaleString()}` : ''}${positions != null ? ` | Positions: ${positions}` : ''}`}
    >
      {connected ? (
        <Wifi className="w-2.5 h-2.5" strokeWidth={2} />
      ) : (
        <WifiOff className="w-2.5 h-2.5" strokeWidth={2} />
      )}
      <span>
        MT5 {connected ? 'Live' : status === 'DISCONNECTED' ? 'Disc.' : status === 'ERROR' ? 'Error' : 'Unknown'}
      </span>
      {equity != null && (
        <span className="opacity-60 font-mono ml-0.5">${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
      )}
    </div>
  )
}