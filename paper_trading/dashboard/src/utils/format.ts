export function formatAssetPrice(price: number | null | undefined): string {
  if (price == null || isNaN(price)) return '—'

  const abs = Math.abs(price)
  let dp: number
  if (abs >= 10000) dp = 0
  else if (abs >= 1000) dp = 2
  else if (abs >= 100) dp = 3
  else if (abs >= 1) dp = 4
  else if (abs >= 0.01) dp = 5
  else dp = 6

  return price.toLocaleString(undefined, {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })
}

export function safeToFixed(value: unknown, digits: number, fallback = '—'): string {
  if (typeof value !== 'number' || !isFinite(value)) return fallback
  return value.toFixed(digits)
}

export function clampPercent(value: number | null | undefined): number {
  if (value == null || !isFinite(value)) return 0
  return Math.min(100, Math.max(0, value))
}

export function confidenceToPercent(value: number | null | undefined): number {
  if (value == null || !isFinite(value)) return 0
  return clampPercent(value <= 1 ? value * 100 : value)
}

export function formatHeldDuration(bars?: number | null): string {
  if (bars == null || bars < 0) return '—'
  if (bars < 1) return '<1d'
  const days = Math.floor(bars)
  const hours = Math.round((bars - days) * 24)
  if (days === 0) return `${hours}h`
  if (hours === 0) return `${days}d`
  return `${days}d ${hours}h`
}

export function formatTimeAgo(isoString: string): string {
  const now = Date.now()
  const then = new Date(isoString).getTime()
  if (isNaN(then)) return 'unknown'
  const seconds = Math.floor((now - then) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || !isFinite(value)) return '—'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}%`
}
