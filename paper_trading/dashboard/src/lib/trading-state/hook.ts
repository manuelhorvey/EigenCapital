import { useMemo } from "react"
import { useSystemSnapshot } from "../../hooks/useSystemSnapshot"
import { toAssetTradingState, toPortfolioTradingState } from "./selectors"
import type { SystemBundle } from "../../types/bundle"
import type { AssetTradingState, PortfolioTradingState } from "./types"

export interface TradingStateResult {
  portfolio: PortfolioTradingState
  assets: Record<string, AssetTradingState>
  assetList: AssetTradingState[]
  isLoading: boolean
  isError: boolean
}

export function useTradingState(): TradingStateResult {
  const { data: bundle, isLoading, isError } = useSystemSnapshot()

  const result = useMemo<TradingStateResult | null>(() => {
    if (!bundle) return null

    const snapshot = bundle.snapshot
    const rawAssets = snapshot.assets ?? {}
    const portfolio = snapshot.portfolio
    const live = bundle.live
    const edgeHealth = (portfolio as any)?.edge_health ?? null

    // Transform each asset
    const assets: Record<string, AssetTradingState> = {}
    for (const [name, raw] of Object.entries(rawAssets)) {
      assets[name] = toAssetTradingState(name, raw, edgeHealth)
    }

    // Build portfolio-level state
    const portfolioState = toPortfolioTradingState(portfolio, assets, live)

    return {
      portfolio: portfolioState,
      assets,
      assetList: Object.values(assets),
      isLoading: false,
      isError: false,
    }
  }, [bundle])

  // If we have no data but aren't erroring, return loading state
  if (!result) {
    return {
      portfolio: null as any,
      assets: {},
      assetList: [],
      isLoading: isLoading,
      isError: isError,
    }
  }

  // Forward loading/error from underlying hook
  return { ...result, isLoading: result.isLoading || isLoading, isError: result.isError || isError }
}
