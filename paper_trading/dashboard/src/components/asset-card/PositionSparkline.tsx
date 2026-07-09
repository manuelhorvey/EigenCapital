import { useMemo } from 'react'

interface PositionSparklineProps {
  /** Recent close prices since position opened (oldest -> newest). */
  prices: number[]
  /** Entry price — drawn as a dashed horizontal line. */
  entry: number
  /** Take-profit price — entry zone shaded green if present. */
  tp: number | null
  /** Stop-loss price — entry zone shaded red if present. */
  sl: number | null
  /** Long uses green-toward-TP convention; short inverts colors. */
  side: 'long' | 'short'
  /** Pixel height. Default 32. */
  height?: number
}

/**
 * Mini price sparkline for an open position card.
 * Renders TP/SL entry zones, an entry anchor line, and a tick area below.
 * Returns null when there are fewer than 4 samples (too noisy to be useful).
 */
export default function PositionSparkline({
  prices,
  entry,
  tp,
  sl,
  side,
  height = 32,
}: PositionSparklineProps) {
  const view = useMemo(() => {
    if (prices.length < 4) return null

    const slNum = sl ?? null
    const tpNum = tp ?? null
    const bounds: number[] = [entry, ...prices]
    if (slNum != null) bounds.push(slNum)
    if (tpNum != null) bounds.push(tpNum)

    const min = Math.min(...bounds)
    const max = Math.max(...bounds)
    const range = max - min || 1
    const pad = range * 0.08
    const yMin = min - pad
    const yMax = max + pad
    const yRange = yMax - yMin

    return { min: yMin, max: yMax, range: yRange }
  }, [prices, entry, tp, sl])

  if (!view) return null

  const width = 100
  const heightPx = height
  const stepX = prices.length > 1 ? width / (prices.length - 1) : width

  const yFor = (v: number) =>
    heightPx - ((v - view.min) / view.range) * heightPx

  // Path: cap height at 95% so the line never touches the box edges.
  const linePath = prices
    .map((v, i) => {
      const x = i * stepX
      const rawY = yFor(v)
      const clampedY = Math.max(1, Math.min(heightPx - 1, rawY))
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${clampedY.toFixed(2)}`
    })
    .join(' ')

  const lastPoint = {
    x: (prices.length - 1) * stepX,
    y: Math.max(1, Math.min(heightPx - 1, yFor(prices[prices.length - 1]))),
  }

  // Line color: grew toward TP = green, moved away from TP = red.
  const toward = side === 'long'
    ? prices[prices.length - 1] >= entry
    : prices[prices.length - 1] <= entry
  const lineColor = toward ? 'var(--color-gov-green)' : 'var(--color-gov-red)'
  const lineColorMuted = toward ? 'var(--color-gov-green-muted)' : 'var(--color-gov-red-muted)'

  // Bands: TP zone shade (side), SL zone shade (opposite of TP), entry line.
  const tpY = tp != null ? yFor(tp) : null
  const slY = sl != null ? yFor(sl) : null
  const entryY = yFor(entry)

  // Decide entry-zone bands relative to entry (so the picture isn't cluttered).
  // TP-zone stretches from entry to TP, SL-zone from entry to SL.
  const tpZone = tp != null ? (
    <rect
      key="tp-zone"
      x={0}
      y={Math.min(entryY, tpY!)}
      width={width}
      height={Math.abs(entryY - tpY!)}
      fill="var(--color-gov-green)"
      fillOpacity={0.08}
    />
  ) : null
  const slZone = sl != null ? (
    <rect
      key="sl-zone"
      x={0}
      y={Math.min(entryY, slY!)}
      width={width}
      height={Math.abs(entryY - slY!)}
      fill="var(--color-gov-red)"
      fillOpacity={0.08}
    />
  ) : null

  return (
    <div
      className="relative w-full"
      style={{ height: heightPx }}
      aria-label="Position price trajectory"
    >
      <svg
        viewBox={`0 0 ${width} ${heightPx}`}
        preserveAspectRatio="none"
        className="w-full h-full overflow-visible"
      >
        {slZone}
        {tpZone}
        <line
          x1={0}
          x2={width}
          y1={entryY}
          y2={entryY}
          stroke="var(--color-text-tertiary)"
          strokeWidth={0.6}
          strokeDasharray="2 2"
          opacity={0.7}
        />
        <path
          d={linePath}
          fill="none"
          stroke={lineColor}
          strokeWidth={1.25}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle
          cx={lastPoint.x}
          cy={lastPoint.y}
          r={1.5}
          fill={lineColor}
        />
        <circle
          cx={lastPoint.x}
          cy={lastPoint.y}
          r={3}
          fill={lineColorMuted}
          opacity={0.35}
        />
      </svg>
    </div>
  )
}
