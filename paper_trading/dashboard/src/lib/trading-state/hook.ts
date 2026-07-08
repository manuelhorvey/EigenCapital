import { useMemo, useState } from "react"
import { useSystemSnapshot } from "../../hooks/useSystemSnapshot"
import { toAssetTradingState, toPortfolioTradingState, type SortKey } from "./selectors"
import type { AssetTradingState, PortfolioTradingState } from "./types"

export interface TradingStateResult {
  portfolio: PortfolioTradingState
  assets: Record<string, AssetTradingState>
  assetList: AssetTradingState[]
  /** Sort key and direction for the asset list. */
  sortKey: SortKey
  sortAsc: boolean
  setSortKey: (key: SortKey) => void
  toggleSortDirection: () => void
  isLoading: boolean
  isError: boolean
}

const RISK_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }
const EXIT_PHASE_ORDER: Record<string, number> = { TRAILING: 0, BREAKEVEN: 1, DECAY: 2, STATIC: 3 }

function sortAssets(
  list: AssetTradingState[],
  key: SortKey,
  asc: boolean,
): AssetTradingState[] {
  const dir = asc ? 1 : -1
  return [...list].sort((a, b) => {
    let cmp = 0
    switch (key) {
      case "name":
        cmp = a.identity.localeCompare(b.identity)
        break
      case "risk":
        cmp = (RISK_ORDER[a.risk_state.level] ?? 2) - (RISK_ORDER[b.risk_state.level] ?? 2)
        break
      case "pnl":
        cmp = a.pnl_state.unrealized - b.pnl_state.unrealized
        break
      case "exit_phase":
        cmp = (EXIT_PHASE_ORDER[a.exit_state.phase] ?? 3) - (EXIT_PHASE_ORDER[b.exit_state.phase] ?? 3)
        break
    }
    return cmp * dir
  })
}

export function useTradingState(): TradingStateResult {
  const { data: bundle, isLoading, isError } = useSystemSnapshot()
  const [sortKey, setSortKey] = useState<SortKey>("risk")
  const [sortAsc, setSortAsc] = useState(false)

  const result = useMemo<TradingStateResult | null>(() => {
    if (!bundle) return null

    const snapshot = bundle.snapshot
    const rawAssets = snapshot.assets ?? {}
    const portfolio = snapshot.portfolio
    const openPositions = snapshot.open_positions ?? {}
    const live = bundle.live
    const edgeHealth = portfolio?.edge_health ?? null

    // Transform each asset
    const assets: Record<string, AssetTradingState> = {}
    for (const [name, raw] of Object.entries(rawAssets)) {
      assets[name] = toAssetTradingState(name, raw, openPositions[name], edgeHealth)
    }

    // Build portfolio-level state
    const portfolioState = toPortfolioTradingState(portfolio, assets, live)
    const assetList = Object.values(assets)

    return {
      portfolio: portfolioState,
      assets,
      assetList: sortAssets(assetList, sortKey, sortAsc),
      sortKey,
      sortAsc,
      setSortKey,
      toggleSortDirection: () => setSortAsc((v) => !v),
      isLoading: false,
      isError: false,
    }
  }, [bundle, sortKey, sortAsc])

  // If we have no data but aren't erroring, return loading state
  if (!result) {
    const shimPortfolio: PortfolioTradingState = {
      system_status: "SAFE",
      pnl: { total: 0, efficiency: 0 },
      risk: { drawdown: 0, net_exposure: 0, concentration_risk: "LOW" },
      execution: { mt5_sync: "DEGRADED", sl_sync_integrity: "OK" },
      alpha: { reversal_rate: null, edge_trend: "STABLE" },
      alerts: [],
      top_3_risks: [],
      recent_events: [],
    }
    return {
      portfolio: shimPortfolio,
      assets: {},
      assetList: [],
      sortKey,
      sortAsc,
      setSortKey,
      toggleSortDirection: () => setSortAsc((v) => !v),
      isLoading: isLoading,
      isError: isError,
    }
  }

  // Forward loading/error from underlying hook
  return { ...result, isLoading: result.isLoading || isLoading, isError: result.isError || isError }
}
