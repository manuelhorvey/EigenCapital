export function formatAssetPrice(price: number | null | undefined): string {
  if (price == null) return '—'

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
