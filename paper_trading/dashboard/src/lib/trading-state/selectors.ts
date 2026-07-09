import type { z } from 'zod'
import { AssetStateSchema, PortfolioSummarySchema, EdgeHealthSummarySchema } from "../../lib/schemas"

type AssetState = z.infer<typeof AssetStateSchema>
type Portfolio = z.infer<typeof PortfolioSummarySchema>
type EdgeHealthSummary = z.infer<typeof EdgeHealthSummarySchema>
import type {
  AssetTradingState,
  PortfolioTradingState,
  ExitPhase,
  RiskLevel,
  EdgeTrend,
  SystemStatus,
  Mt5SyncStatus,
} from "./types"

// ── Helper ─────────────────────────────────────────────────────────

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function efficiencyToNumeric(efficiency: AssetTradingState["pnl_state"]["efficiency"]): number {
  if (efficiency === "HIGH") return 0.8
  if (efficiency === "NORMAL") return 0.5
  return 0.2
}

// ── Domain types ───────────────────────────────────────────────────

export type SortKey = "name" | "risk" | "pnl" | "exit_phase"

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
interface LiveBundle {
  mt5?: { connected?: boolean }
}

/** Open position data with optional adaptive exit fields. */
interface OpenPositionData {
  adaptive_exit_phase?: string
  peak_mfe_r?: number | null
  sl_update_count?: number
  r_multiple?: number
  direction?: string
  current_value?: number
  position?: {
    side?: string
    entry?: number
    sl?: number
    tp?: number
    vol?: number
  }
}

// ── Driver title map ───────────────────────────────────────────────

const DRIVER_TITLES: Record<string, string> = {
  drawdown: "Drawdown pressure high",
  tripwire: "Tripwire active",
  sell_only_filter: "SELL_ONLY filter active",
  halted: "Asset halted",
}

const DRIVER_SEVERITY: Record<string, "CRITICAL" | "HIGH" | "MEDIUM"> = {
  drawdown: "HIGH",
  tripwire: "HIGH",
  sell_only_filter: "MEDIUM",
  halted: "CRITICAL",
}

// ── Asset-level selector ───────────────────────────────────────────

export function toAssetTradingState(
  assetName: string,
  raw: AssetState,
  openPos?: OpenPositionData | null,
  edgeHealth?: EdgeHealthSummary | null,
): AssetTradingState {
  const pos = raw.metrics.position

  // ── Position state ───────────────────────────────────────────
  const halted = raw.halt.halted
  const hasPosition = pos !== null || openPos != null

  const positionState: AssetTradingState["position_state"] = halted
    ? "HALTED"
    : hasPosition
      ? "OPEN"
      : "CLOSED"

  const direction: AssetTradingState["direction"] =
    pos?.side === "long" ? "LONG"
    : pos?.side === "short" ? "SHORT"
    : openPos?.position?.side === "long" ? "LONG"
    : openPos?.position?.side === "short" ? "SHORT"
    : null

  // ── PnL state ────────────────────────────────────────────────
  const unrealized = pos?.unrealized_pnl ?? 0
  const avgR = raw.metrics.exit_reasons?.avg_r ?? 0

  const peakMfeR: number | null = openPos?.peak_mfe_r ?? null
  const exitPhase: ExitPhase = (openPos?.adaptive_exit_phase as ExitPhase) ?? "STATIC"
  const isActive = exitPhase !== "STATIC"
  const slUpdateCount = openPos?.sl_update_count ?? 0

  // Estimate r_multiple from position data if available
  let rMultiple: number | null = null
  if (isActive && peakMfeR != null && peakMfeR > 0 && pos?.entry && pos?.unrealized_pnl && pos?.current_vol) {
    // unrealized_pnl / (entry * vol) ≈ r_multiple for linear products
    rMultiple = Math.abs(pos.unrealized_pnl) / Math.max(pos.entry * pos.current_vol, 1e-9)
  }

  let efficiency: AssetTradingState["pnl_state"]["efficiency"] = "NORMAL"
  if (peakMfeR != null && rMultiple != null && peakMfeR > 0) {
    const ratio = rMultiple / peakMfeR
    efficiency = ratio >= 0.7 ? "HIGH" : ratio >= 0.4 ? "NORMAL" : "LOW"
  }

  let retracementPct: number | null = null
  if (isActive && peakMfeR != null && peakMfeR > 0 && openPos?.current_value != null && openPos.position?.entry != null) {
    // Estimate retracement from current value vs peak
    const entryVal = Math.abs(openPos.position.entry * (openPos.position.vol ?? 1))
    const peakVal = Math.abs(peakMfeR * entryVal)
    const currentVal = Math.abs(openPos.current_value)
    if (peakVal > entryVal) {
      retracementPct = clamp(1 - (currentVal - entryVal) / (peakVal - entryVal), 0, 1)
    }
  }

  // ── Risk state ───────────────────────────────────────────────
  const monthlyPf = raw.metrics.monthly_pf ?? 0.1
  const rawDrawdown = raw.metrics.drawdown ?? 0
  const drawdownPressure = clamp(
    Math.abs(rawDrawdown) / Math.max(Math.abs(monthlyPf), 0.01),
    0,
    1,
  )

  const drivers: string[] = []
  if (drawdownPressure > 0.7) drivers.push("drawdown")
  if (raw.tripwire_active) drivers.push("tripwire")
  if (raw.sell_only) drivers.push("sell_only_filter")
  if (halted) drivers.push("halted")

  let riskLevel: RiskLevel = "LOW"
  if (drawdownPressure > 0.7) riskLevel = "HIGH"
  else if (drawdownPressure > 0.3) riskLevel = "MEDIUM"

  // ── Alpha state ──────────────────────────────────────────────
  let mfeCaptureQuality: number | null = null
  if (peakMfeR != null && peakMfeR > 0 && rMultiple != null) {
    mfeCaptureQuality = clamp(rMultiple / peakMfeR, 0, 1)
  }

  const reversalProbability: number | null = edgeHealth?.reversal_rate ?? null

  // ── Flags ────────────────────────────────────────────────────
  const flags: string[] = [...drivers]
  if (exitPhase !== "STATIC" && !slUpdateCount) {
    flags.push("ADAPTIVE_EXIT_UNCONFIRMED")
  }

  return {
    identity: assetName,
    position_state: positionState,
    direction,
    pnl_state: {
      unrealized,
      avg_r: avgR,
      efficiency,
    },
    exit_state: {
      phase: exitPhase,
      is_active: isActive,
      peak_mfe_r: peakMfeR,
      retracement_pct: retracementPct,
      sl_is_dynamic: slUpdateCount > 0,
      sl_confirmed_broker: true,
    },
    risk_state: {
      level: riskLevel,
      drawdown_pressure: drawdownPressure,
      drivers,
    },
    alpha_state: {
      mfe_capture_quality: mfeCaptureQuality,
      reversal_probability: reversalProbability,
    },
    flags,
    recent_events: [],
  }
}

// ── Portfolio-level selector ──────────────────────────────────────

export function toPortfolioTradingState(
  portfolio: Portfolio,
  assets: Record<string, AssetTradingState>,
  live?: LiveBundle | null,
): PortfolioTradingState {
  const assetList = Object.values(assets)

  // ── System status ────────────────────────────────────────────
  const anyHalted = assetList.some((a) => a.position_state === "HALTED")
  const highRiskCount = assetList.filter((a) => a.risk_state.level === "HIGH").length

  let systemStatus: SystemStatus = "SAFE"
  if (anyHalted) systemStatus = "ALERT"
  else if (highRiskCount > 3) systemStatus = "MONITOR"

  // ── PnL ──────────────────────────────────────────────────────
  // total_return from backend is a percentage (2.5 for 2.5%)
  const pnlTotal = portfolio.total_return ?? 0

  const effSum = assetList.reduce((sum, a) => sum + efficiencyToNumeric(a.pnl_state.efficiency), 0)
  const pnlEfficiency = assetList.length > 0 ? effSum / assetList.length : 0

  // ── Risk ─────────────────────────────────────────────────────
  // portfolio_drawdown from backend is a fraction (0-1 range)
  const drawdownPct = portfolio.portfolio_drawdown ?? 0
  const drawdown = Math.abs(drawdownPct)

  const longCount = assetList.filter((a) => a.direction === "LONG").length
  const shortCount = assetList.filter((a) => a.direction === "SHORT").length
  const totalAssets = assetList.length
  const netExposure = totalAssets > 0 ? (longCount - shortCount) / totalAssets : 0

  const conc = portfolio.position_concentration
  const skew = conc?.skew ?? 0
  const absSkew = Math.abs(skew)
  let concentrationRisk: RiskLevel = "LOW"
  if (absSkew > 0.7) concentrationRisk = "HIGH"
  else if (absSkew > 0.4) concentrationRisk = "MEDIUM"

  // ── Execution ────────────────────────────────────────────────
  const mt5Connected = live?.mt5?.connected ?? false
  const mt5Sync: Mt5SyncStatus = mt5Connected ? "HEALTHY" : "DEGRADED"

  const slIntegrityOk = !assetList.some(
    (a) => a.exit_state.sl_is_dynamic && !a.exit_state.sl_confirmed_broker,
  )
  const slSyncIntegrity: "OK" | "WARNING" = slIntegrityOk ? "OK" : "WARNING"

  // ── Alpha ────────────────────────────────────────────────────
  const portfolioEdgeHealth = portfolio.edge_health ?? null
  const reversalRate: number | null = portfolioEdgeHealth?.reversal_rate ?? null

  let edgeTrend: EdgeTrend = "STABLE"
  if (reversalRate !== null) {
    if (reversalRate < 0.15) edgeTrend = "EXPANDING"
    else if (reversalRate < 0.35) edgeTrend = "STABLE"
    else edgeTrend = "DECAYING"
  }

  // ── Alerts ───────────────────────────────────────────────────
  const alerts: string[] = []
  if (systemStatus === "ALERT") alerts.push("System halted")
  if (!slIntegrityOk) alerts.push("Broker SL sync may be degraded")
  if (drawdown > 0.05) alerts.push("Portfolio drawdown elevated")

  // ── Top 3 risks ──────────────────────────────────────────────
  const driverFreq: Record<string, number> = {}
  for (const a of assetList) {
    for (const d of a.risk_state.drivers) {
      driverFreq[d] = (driverFreq[d] ?? 0) + 1
    }
  }
  const topDrivers = Object.entries(driverFreq)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  const top3Risks: PortfolioTradingState["top_3_risks"] = topDrivers.map(([driver]) => ({
    title: DRIVER_TITLES[driver] ?? `Risk: ${driver}`,
    severity: DRIVER_SEVERITY[driver] ?? "HIGH",
  }))

  return {
    system_status: systemStatus,
    pnl: {
      total: pnlTotal,
      efficiency: pnlEfficiency,
    },
    risk: {
      drawdown,
      net_exposure: netExposure,
      concentration_risk: concentrationRisk,
    },
    execution: {
      mt5_sync: mt5Sync,
      sl_sync_integrity: slSyncIntegrity,
    },
    alpha: {
      reversal_rate: reversalRate,
      edge_trend: edgeTrend,
    },
    alerts,
    top_3_risks: top3Risks,
    recent_events: [],
  }
}
