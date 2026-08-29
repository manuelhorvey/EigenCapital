const API_BASE = '/api/v1';

export async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

// System
export const getSystemHealth = () => fetchApi<SystemHealthResponse>('/system/health');
export const getBuildIdentity = () => fetchApi<BuildIdentity>('/system/build');
export const getSystemInfo = () => fetchApi<SystemInfo>('/system/info');

// Health
export const getHealth = () => fetchApi<HealthState>('/health');
export const getAuthorization = () => fetchApi<Authorization>('/health/authorization');
export const getWatchdog = () => fetchApi<Watchdog>('/health/watchdog');

// Portfolio
export const getAccount = () => fetchApi<Account>('/portfolio/account');
export const getPositions = () => fetchApi<Position[]>('/portfolio/positions');
export const getPortfolioSummary = () => fetchApi<PortfolioSummary>('/portfolio/summary');

// Risk
export const getRiskState = () => fetchApi<RiskState>('/risk');
export const getRiskEnvelope = () => fetchApi<RiskEnvelope>('/risk/envelope');

// Evidence
export const getEvents = (page = 1, pageSize = 50) =>
  fetchApi<EventTimeline>(`/evidence/events?page=${page}&page_size=${pageSize}`);
export const getQualification = () => fetchApi<Qualification>('/evidence/qualification');
export const getShadowReduced = () => fetchApi<ShadowReduced>('/evidence/shadow-reduced');

// Alerts
export const getAlerts = (limit = 50) =>
  fetchApi<Alert[]>(`/alerts?limit=${limit}`);

// Reconciliation
export const getReconciliation = () => fetchApi<ReconciliationStatus>('/reconciliation');

// ─── Types ───────────────────────────────────────────────────────────

// Freshness is a first-class concept
export type Freshness = "LIVE" | "STALE" | "UNKNOWN";

export interface SystemHealthResponse {
  status: string;
  overall_state: string;
  trading_authorization: string;
  timestamp: string;
}

export interface BuildIdentity {
  git_head: string;
  manifest_identity: string;
  config_fingerprint: string;
  loop_script_sha256: string;
  build_id: string;
  verified: boolean;
  drift_detected: boolean;
  drift_details: Record<string, unknown>;
  timestamp: string;
  freshness: Freshness;
}

export interface SystemInfo {
  dashboard_version: string;
  read_only: boolean;
  can_submit_orders: boolean;
  can_modify_r4: boolean;
  can_modify_risk_limits: boolean;
  can_activate_reduced: boolean;
  timestamp: string;
}

export interface HealthDimension {
  dimension: string;
  state: string;
  message: string;
  timestamp: string;
  last_change: string | null;
  consecutive_failures: number;
  details: Record<string, unknown>;
}

export interface HealthState {
  overall_state: string;
  trading_authorization: string;
  dimensions: HealthDimension[];
  blocking_dimensions: string[];
  timestamp: string;
  freshness: Freshness;
}

export interface Authorization {
  status: string;
  authorization_id: string | null;
  campaign_id: string | null;
  execution_mode: string;
  max_capital: number | null;
  max_drawdown: number | null;
  authorization_timestamp: string | null;
  expiry_timestamp: string | null;
  fingerprint_status: string;
  timestamp: string;
}

export interface Watchdog {
  state: string;
  previous_state: string | null;
  authorize_trading: boolean;
  authorize_flatten_on_reconnect: boolean;
  reason: string;
  last_transition: string | null;
  evidence: Record<string, unknown>;
}

export interface Account {
  equity: number;
  balance: number;
  free_margin: number;
  margin_used: number;
  margin_utilization: number;
  equity_high_water: number;
  drawdown: number;
  drawdown_pct: number;
  daily_pnl: number;
  daily_loss_remaining: number;
  unrealized_pnl: number;
  currency: string;
  timestamp: string;
  freshness: Freshness;
  source: string;
}

export interface Position {
  ticket: number;
  symbol: string;
  direction: string;
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss: number | null;
  distance_to_sl: number | null;
  mae: number | null;
  mfe: number | null;
  holding_time: string | null;
  risk_state: string;
  protected: boolean;
  attribution_state: string | null;
  last_update: string;
  freshness: Freshness;
  source: string;
}

export interface PortfolioSummary {
  position_count: number;
  long_count: number;
  short_count: number;
  gross_exposure: number;
  net_exposure: number;
  exposure_pct: number;
  concentration: number;
  largest_position_symbol: string | null;
  protected_count: number;
  unprotected_count: number;
  timestamp: string;
}

export interface RiskObservation {
  dimension: string;
  level: string;
  value: number;
  limit: number | null;
  utilization: number | null;
  message: string;
  timestamp: string;
  details: Record<string, unknown>;
  trend: string | null;
}

export interface RiskState {
  overall_level: string;
  observations: RiskObservation[];
  any_critical: boolean;
  any_warning: boolean;
  critical_dimensions: string[];
  warning_dimensions: string[];
  timestamp: string;
  freshness: Freshness;
}

export interface RiskEnvelope {
  max_concurrent_positions: number;
  max_position_notional: number;
  max_order_notional: number;
  max_per_position_loss_pct: number;
  max_account_drawdown_pct: number;
  max_daily_loss: number;
  min_equity: number;
  require_sl_on_positions: boolean;
  t0_equity: number;
}

export interface EventTimeline {
  events: Event[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  oldest_timestamp: string | null;
  newest_timestamp: string | null;
}

export interface Event {
  event_id: string;
  event_type: string;
  timestamp: string;
  symbol: string | null;
  ticket: number | null;
  correlation_id: string | null;
  severity: string | null;
  message: string;
  details: Record<string, unknown>;
  build_id: string | null;
  strategy_version: string | null;
}

export interface EvidenceMaturity {
  e0_count: number;
  e1_count: number;
  e2_count: number;
  e3_count: number;
  e4_count: number;
  e5_count: number;
  e6_count: number;
  total_trades: number;
  open_trades: number;
  completed_lifecycles: number;
  observation_days: number;
  timestamp: string;
}

export interface QualificationGate {
  gate_id: string;
  name: string;
  status: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface Qualification {
  campaign_id: string;
  campaign_start: string | null;
  evidence_maturity: EvidenceMaturity;
  gates: QualificationGate[];
  overall_status: string;
  evidence_insufficient: boolean;
  timestamp: string;
  freshness: Freshness;
}

export interface ShadowReduced {
  mode: string;
  observations: number;
  hypothetical_reductions: number;
  average_scale: number | null;
  actual_size: number | null;
  hypothetical_size: number | null;
  actual_pnl: number | null;
  hypothetical_pnl: number | null;
  counterfactual_difference: number | null;
  label: string;
  timestamp: string;
  freshness: Freshness;
}

export interface Alert {
  alert_id: string;
  timestamp: string;
  severity: string;
  category: string;
  event_type: string;
  message: string;
  event_id: string | null;
  correlation_id: string | null;
  state_transition: string | null;
  consecutive_count: number;
  details: Record<string, unknown>;
  acknowledged: boolean;
}

export interface ReconciliationStatus {
  overall_status: string;
  last_reconciliation: string | null;
  checks_performed: number;
  checks_passed: number;
  checks_warning: number;
  checks_critical: number;
  checks_blocking: number;
  stale_positions: number;
  missing_fills: number;
  duplicate_orders: number;
  foreign_positions: number;
  timestamp: string;
  freshness: Freshness;
}
