import { useQueries } from '@tanstack/react-query'
import { Wifi, WifiOff, AlertTriangle } from 'lucide-react'

const ENDPOINTS = [
  { key: 'state', url: '/state.json', threshold: 35_000 },
  { key: 'governance', url: '/governance.json', threshold: 35_000 },
  { key: 'psi', url: '/psi.json', threshold: 65_000 },
  { key: 'liquidity', url: '/liquidity.json', threshold: 65_000 },
  { key: 'narrative', url: '/narrative.json', threshold: 305_000 },
] as const

type StatusLevel = 'live' | 'degraded' | 'offline'

export default function ConnectionStatus() {
  const results = useQueries({
    queries: ENDPOINTS.map(ep => ({
      queryKey: [ep.key, 'health'],
      queryFn: async () => {
        const start = Date.now()
        const res = await fetch(ep.url, { method: 'HEAD' })
        return { ok: res.ok, latency: Date.now() - start }
      },
      refetchInterval: 30_000,
      staleTime: 25_000,
      retry: false,
    })),
  })

  const now = Date.now()
  let status: StatusLevel = 'live'
  let totalEndpoints = ENDPOINTS.length
  let healthyCount = 0
  let degradedCount = 0
  let offlineCount = 0

  for (let i = 0; i < results.length; i++) {
    const r = results[i]
    if (r.isError) {
      offlineCount++
      status = 'offline'
    } else if (r.dataUpdatedAt && (now - r.dataUpdatedAt) > ENDPOINTS[i].threshold) {
      degradedCount++
      if (status !== 'offline') status = 'degraded'
    } else if (r.data?.ok) {
      healthyCount++
    }
  }

  const barColor = status === 'live'
    ? 'bg-gov-green'
    : status === 'degraded'
      ? 'bg-gov-yellow'
      : 'bg-gov-red'

  const textColor = status === 'live'
    ? 'text-gov-green'
    : status === 'degraded'
      ? 'text-gov-yellow'
      : 'text-gov-red'

  const label = status === 'live' ? 'Live'
    : status === 'degraded' ? 'Degraded'
    : 'Offline'

  const Icon = status === 'live' ? Wifi
    : status === 'degraded' ? AlertTriangle
    : WifiOff

  return (
    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-transparent ${textColor}`}
      title={`${healthyCount}/${totalEndpoints} healthy · ${degradedCount} degraded · ${offlineCount} offline`}
    >
      <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${barColor} ${status === 'live' ? 'animate-pulse' : ''}`}>
        {status === 'live' && (
          <span className="absolute inset-0 rounded-full bg-current animate-ping opacity-30" />
        )}
      </span>
      <Icon className="w-2.5 h-2.5" strokeWidth={2.5} />
      <span className="text-2xs font-semibold font-mono uppercase tracking-wide">{label}</span>
    </div>
  )
}
