// ── Enums / string unions ──────────────────────────────────────────

/** Current phase of the adaptive exit engine for a position. */
export type ExitPhase = "BREAKEVEN" | "TRAILING" | "DECAY" | "STATIC"

/** Subjective risk level — derived from drawdown, concentration, and volatility. */
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH"

/** Whether the model's edge is improving, stable, or deteriorating over recent trades. */
export type EdgeTrend = "EXPANDING" | "STABLE" | "DECAYING"

/** Overall health colour for the system — displayed as a top-level badge. */
export type SystemStatus = "SAFE" | "MONITOR" | "ALERT"

/** Sync health of the MT5 bridge — reflects connection + position reconciliation. */
export type Mt5SyncStatus = "HEALTHY" | "DEGRADED" | "FAILED"

// ── System events (minimal for now) ────────────────────────────────

/** Discriminated union key — used to render event timeline entries. */
export type SystemEventType =
  | "EXIT_PHASE_CHANGED"
  | "SL_UPDATED"
  | "BREAKEVEN_LOCKED"
  | "TRAILING_ACTIVATED"
  | "EDGE_HEALTH_ALERT"

/**
 * A single interpreted event emitted by the TUIL layer.
 * `recent_events` on both AssetTradingState and PortfolioTradingState
 * is a small ring buffer (max ~20). This is not a log — it is a
 * rolling window of recent noteworthy transitions.
 */
export interface SystemEvent {
  type: SystemEventType
  /** Unix ms timestamp of when the event was observed. */
  timestamp: number
  /** Optional asset ticker — absent for portfolio-level events. */
  asset?: string
}

// ── Asset-level interpreted state ───────────────────────────────────

/**
 * Per-asset interpreted state.
 *
 * Fields are intentionally flat so the UI can read them without
 * deeply nesting lookups. Each sub-object groups a concern area:
 * PnL, exit mechanics, risk, alpha quality.
 */
export interface AssetTradingState {
  /** Asset ticker (e.g. "EURUSD"). Matches `AssetState.metrics.asset`. */
  identity: string

  /** Whether the engine currently holds a position for this asset. */
  position_state: "OPEN" | "CLOSED" | "HALTED"

  /** Direction of the current or last position. Null when flat with no history. */
  direction: "LONG" | "SHORT" | null

  /** PnL-derived signals for the asset. */
  pnl_state: {
    /** Unrealised PnL in account currency. */
    unrealized: number
    /** Average R-multiple from closed trades. */
    avg_r: number
    /** Subjective efficiency — based on how much of peak MFE was captured. */
    efficiency: "LOW" | "NORMAL" | "HIGH"
  }

  /** Current state of the adaptive exit engine. */
  exit_state: {
    /** Which exit phase is active (STATIC if adaptive exit is disabled). */
    phase: ExitPhase
    /** Whether the engine is currently monitoring this position. */
    is_active: boolean
    /** Peak MFE in R-multiples observed during this trade, if any. */
    peak_mfe_r: number | null
    /** Current retracement from peak MFE as a fraction [0–1], if trailing is active. */
    retracement_pct: number | null
    /** Whether the SL has been moved from the original static level. */
    sl_is_dynamic: boolean
    /** Whether the latest SL update has been confirmed by the broker. */
    sl_confirmed_broker: boolean
  }

  /** Computed risk signals derived from drawdown, volatility, and governance state. */
  risk_state: {
    level: RiskLevel
    /** Normalised drawdown pressure [0–1] for this asset. */
    drawdown_pressure: number
    /** Human-readable reasons for the risk level (e.g. "drawdown", "regime_sl", "tripwire"). */
    drivers: string[]
  }

  /** Alpha / model-quality signals. */
  alpha_state: {
    /** Fraction of peak MFE captured [0–1] across recent trades. Null when no trades. */
    mfe_capture_quality: number | null
    /** Estimated probability that a winning trade reverses before exit [0–1]. Null when unknown. */
    reversal_probability: number | null
  }

  /** Asset-level alert flags (e.g. "HALTED", "TRIPWIRE", "SELL_ONLY", "SL_NOT_CONFIRMED"). */
  flags: string[]

  /** Rolling window of recent SystemEvents for this asset (max ~20 entries). */
  recent_events: SystemEvent[]
}

// ── Portfolio-level interpreted state ──────────────────────────────

/**
 * Portfolio-level interpreted state.
 *
 * Derived by aggregating over all AssetTradingState instances.
 * The top-level badge colour comes from `system_status`.
 */
export interface PortfolioTradingState {
  /** Overall system health — SAFE, MONITOR, or ALERT. */
  system_status: SystemStatus

  /** Aggregated PnL signals. */
  pnl: {
    /** Total portfolio PnL (realised + unrealised) in account currency. */
    total: number
    /** Portfolio-level efficiency — mean of per-asset MFE capture rates. */
    efficiency: number
  }

  /** Aggregated risk signals. */
  risk: {
    /** Current portfolio drawdown in account currency (absolute, not %). */
    drawdown: number
    /** Net directional exposure (long - short) as a fraction of capital. */
    net_exposure: number
    /** Whether the portfolio is concentrated in a single asset or direction. */
    concentration_risk: RiskLevel
  }

  /** Execution-layer health signals. */
  execution: {
    /** MT5 bridge sync status. */
    mt5_sync: Mt5SyncStatus
    /** Overall SL sync integrity — WARNING if any asset has an unconfirmed broker SL. */
    sl_sync_integrity: "OK" | "WARNING"
  }

  /** Portfolio-level alpha signals. */
  alpha: {
    /** Fraction of recent trades that reversed (hit MFE ≥ 1R then hit SL). Null when no data. */
    reversal_rate: number | null
    /** Whether the system's aggregate edge is improving, stable, or decaying. */
    edge_trend: EdgeTrend
  }

  /** Portfolio-level alerts — things a UI operator should know about. */
  alerts: string[]

  /** Top 3 risks ranked by severity for the dashboard's risk panel. */
  top_3_risks: { title: string; severity: "CRITICAL" | "HIGH" | "MEDIUM" }[]

  /** Rolling window of recent portfolio-level SystemEvents (max ~20 entries). */
  recent_events: SystemEvent[]
}
