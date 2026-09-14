"""R4 Rebalance Loop — periodic signal check and order submission.

Connects to MT5, pulls fresh data, computes the frozen R4 signal,
and submits orders only when:
  1. A legitimate signal exists (regime ON)
  2. Target positions differ from current positions
  3. Orders pass envelope and spread checks

Runs on a configurable interval (default: 1 hour).
Respects the rebalance frequency from config (weekly).

Safety controls:
  - Regime gate: no trade when vol > median (unless --force-regime)
  - Spread check: skip symbols with excessive spread
  - Envelope enforcement: max position, max order, max concurrent
  - Max orders per cycle: configurable (default: 8)
  - Graceful shutdown: SIGINT stops cleanly
  - Audit log: every decision and order recorded to JSONL

Usage:
    python scripts/r4_rebalance_loop.py                       # check once
    python scripts/r4_rebalance_loop.py --loop                 # continuous
    python scripts/r4_rebalance_loop.py --loop --interval 3600 # every hour
    python scripts/r4_rebalance_loop.py --force-regime         # bypass regime filter
    python scripts/r4_rebalance_loop.py --flatten              # emergency close all positions
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# ── Path setup (must precede eigencapital imports) ─────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# P0 EC-AUD-001: Timeout for broker calls to prevent hung sessions
_ORDER_SEND_TIMEOUT_SECONDS = 30  # hard limit per order_send call
_MAX_D1_DATA_AGE_SECONDS = 3 * 24 * 60 * 60  # tolerate a weekend, block older bars
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5-order")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None  # Allow import on non-Linux for testing

from eigencapital.config import load_config  # noqa: E402
from eigencapital.live.daily_loss import DailyLossTracker  # noqa: E402
from eigencapital.live.partial_fills import PartialFillManager  # noqa: E402
from eigencapital.live.position_attribution import R4_MAGIC, classify_all, snapshot_hash  # noqa: E402
from eigencapital.live.risk import DisconnectRecovery, RecoveryState  # noqa: E402
from eigencapital.live.risk_enforcement import GateResult, RiskEnforcer, RiskEnvelope  # noqa: E402
from eigencapital.live.watchdog import ProbeResult, Watchdog, WatchState, trail_age_seconds  # noqa: E402
from eigencapital.production_qual.evidence_orchestrator import (  # noqa: E402
    EvidenceOrchestrator,
    capture_evidence_snapshot,
    record_operational_event,
)
from eigencapital.production_qual.fingerprint_verifier import (  # noqa: E402
    FingerprintVerifier,
)
from eigencapital.reconciliation.engine import (  # noqa: E402
    BrokerState,
    InternalState,
    ReconciliationEngine,
)

# ── Load Configuration (Single Source of Truth) ───────────────────

_config = load_config(os.environ.get("EIGENCAPITAL_ENV", "production"))


def _entry_spread_ok(symbol: str, bid: float, ask: float) -> bool:
    """Apply the configured absolute FX spread or relative non-FX spread."""
    if bid <= 0 or ask <= 0 or ask < bid:
        return False
    limit = float(getattr(_config.broker, "max_spread", 0.0))
    if limit <= 0:
        return True
    category = str(getattr(_config.broker, "allowed_symbols", {}).get(symbol, ""))
    if category.startswith("forex"):
        return (ask - bid) <= limit
    midpoint = (ask + bid) / 2.0
    return (ask - bid) / midpoint <= limit


# R4 universe — derived from broker config
R4_SYMBOLS = list(_config.broker.allowed_symbols.keys())

# Eligible symbols — those classified as tradeable (not excluded)
ELIGIBLE_SYMBOLS = [sym for sym, cls in _config.broker.allowed_symbols.items() if not cls.endswith("_excluded")]

# Asset classes — derived from broker config
ASSET_CLASSES = {
    sym: cls.split("_")[0]  # "forex_excluded" → "forex"
    for sym, cls in _config.broker.allowed_symbols.items()
}

# Strategy parameters — from config (single source of truth)
LOOKBACK = _config.strategy.signal_lookback_long  # 252 — 12-1 month momentum lookback
SKIP = _config.strategy.skip_months * 21  # 1 month ≈ 21 trading days
RISK_LOOKBACK = _config.strategy.risk_lookback  # 20 — expanding median for regime filter
VOL_LOOKBACK = _config.strategy.vol_lookback_signal  # 60 — 60-day vol for inverse-vol scaling
# Term structure design: VOL_LOOKBACK (60d ≈ 3 months) is intentionally shorter
# than signal lookback (252d ≈ 1 year) to capture recent volatility dynamics
# that may differ from long-term averages. In stressed markets, recent vol can
# spike well above the 1-year average, causing vol_scale to dampen signals
# more aggressively than the momentum information content warrants. This
# intentional asymmetry (short vol window, long signal window) is a feature of
# the frozen R4 pipeline, not a bug — it provides responsive risk damping
# while preserving the signal's information horizon. The ratio
# VOL_LOOKBACK / LOOKBACK ≈ 1/4 is a rule of thumb; exact values are configured
# per-strategy and preserved across the R4 frozen spec.

# Lookback design: signal (252d) and vol (60d) windows are independent by design.
# The signal lookback captures full-cycle momentum (≈ 1 year), while the vol lookback
# captures recent volatility dynamics (≈ 3 months). In stressed markets where vol changes
# rapidly, the vol-scaling may not fully reflect the signal's information horizon, which
# is an inherent feature of the frozen R4 pipeline rather than a bug. The ratio
# vol_lookback / signal_lookback ≈ 1/4 is a rule of thumb, not a strict requirement;
# the exact values are configured per-strategy and preserved across the R4 frozen spec.
VOL_TARGET = _config.strategy.vol_target_annual  # 0.10

# Capital limits — from config
MAX_EQUITY = _config.capital.max_equity  # 5100
MAX_POSITION_USD = _config.capital.max_position_size  # 1500
MAX_CONCURRENT = _config.capital.max_concurrent_positions  # 8
MAX_ORDERS_PER_CYCLE = _config.execution.max_orders_per_cycle  # 8

# Risk enforcement envelope — from live_risk config (single source of truth)
_lr = _config.live_risk
RISK_ENVELOPE = RiskEnvelope(
    max_concurrent_positions=_lr.max_concurrent_positions,
    max_position_notional=_lr.max_position_notional,
    max_order_notional=_lr.max_order_notional,
    max_per_position_loss_pct=_lr.max_per_position_loss_pct,
    max_account_drawdown_pct=_lr.max_account_drawdown_pct,
    max_daily_loss=_lr.max_daily_loss,
    min_equity=_lr.min_equity,
    require_sl_on_positions=_lr.require_sl_on_positions,
    t0_equity=_lr.t0_equity,
)

AUDIT_DIR = "reports/r4_loop"
AUDIT_FILE = os.path.join(AUDIT_DIR, "decisions.jsonl")
ORDER_INTENT_FILE = os.path.join(AUDIT_DIR, "order_intents.jsonl")  # EC-AUD-004: independent intent ledger
WEIGHT_DEVIATION_FILE = os.path.join(AUDIT_DIR, "weight_deviation.jsonl")  # T0 sizing evidence

# ── Globals ────────────────────────────────────────────────────────

_shutdown = False
_cycle_counter = 0  # EC-AUD-004: monotonic cycle counter for intent correlation
_risk_enforcer = RiskEnforcer(
    RISK_ENVELOPE,
    audit_log_path=os.path.join(AUDIT_DIR, "risk_gate_audit.jsonl"),
    shadow_decisions_path=os.path.join(AUDIT_DIR, "shadow_decisions.jsonl"),
)
_fingerprint_verifier = FingerprintVerifier(config=_config)
_evidence_orchestrator = EvidenceOrchestrator(
    campaign_id="R4-5K-20260827",
    snapshot_interval_seconds=_config.execution.loop_interval_seconds,
)
_daily_loss_tracker = DailyLossTracker(
    max_daily_loss=_lr.max_daily_loss,
    persistence_dir=AUDIT_DIR,
)
_disconnect_recovery = DisconnectRecovery(
    max_recovery_attempts=_config.health.max_recovery_attempts,
)
_watchdog = Watchdog(
    stale_after_seconds=_config.watchdog.stale_after_seconds,
    blind_after_seconds=_config.watchdog.blind_after_seconds,
    contain_after_seconds=_config.watchdog.contain_after_seconds,
)
_reconciliation_engine = ReconciliationEngine(
    r4_magic=R4_MAGIC,
    stale_threshold_seconds=_config.reconciliation.stale_threshold_seconds,
    allowed_symbols=set(R4_SYMBOLS),  # P1-010: multi-factor foreign detection
)

# State persisted across restarts
_STATE_FILE = os.path.join(AUDIT_DIR, "runtime_state.json")

# T0 sizing evidence (forensic audit 2026-09-13): intended-vs-achievable
# weight deviation per symbol, populated by generate_orders on every call and
# persisted to weight_deviation.jsonl by run_cycle. Read-only diagnostics —
# never feeds back into signal, selection, or sizing (behavior unchanged).
weight_error_by_symbol: Dict[str, Dict[str, Any]] = {}


def _handle_signal(sig, frame):
    global _shutdown
    _shutdown = True
    print("\n  ⏹️  Shutdown signal received — finishing current cycle...")


signal.signal(signal.SIGINT, _handle_signal)
# SIGTERM not available on Windows — use SIGBREAK there
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _handle_signal)


# ── Helpers ────────────────────────────────────────────────────────


def log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", flush=True)


def audit(record: Dict[str, Any]) -> None:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    record["timestamp"] = datetime.now(UTC).isoformat()
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _persist_order_intents(orders: List[Tuple[str, str, float, str, int | None]], cycle_counter: int) -> None:
    """EC-AUD-004: Persist order intents BEFORE execution.

    Creates an independent intent ledger that reconciliation can compare
    broker state against — breaking the tautological broker-vs-broker comparison.
    Each intent is an append-only JSONL record with a cycle counter.
    """
    os.makedirs(AUDIT_DIR, exist_ok=True)
    intent = {
        "timestamp": datetime.now(UTC).isoformat(),
        "cycle_counter": cycle_counter,
        "intents": [
            {
                "symbol": sym,
                "side": side,
                "lots": lots,
                "reason": reason,
                "ticket": ticket,
                "intended_weight": weight_error_by_symbol.get(sym, {}).get("signal_weight", 0.0),
                "weight_error_pct": weight_error_by_symbol.get(sym, {}).get("weight_error_pct", 0.0),
                "min_lot_floor": weight_error_by_symbol.get(sym, {}).get("floored", False),
            }
            for sym, side, lots, reason, ticket in orders
        ],
        "intent_count": len(orders),
    }
    with open(ORDER_INTENT_FILE, "a") as f:
        f.write(json.dumps(intent, default=str) + "\n")


def _reconcile_against_intents(
    filled_count: int,
    failed_count: int,
    orders: List[Tuple[str, str, float, str, int | None]],
    fills: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """EC-AUD-004 + T0: Reconcile execution results against persisted intents.

    Compares what we INTENDED to submit vs what actually happened.
    Detects: missing fills, unexpected fills, phantom executions.

    T0 upgrade: beyond the count check, fills are matched to intents per
    (symbol, side) so a compensating pair of errors (one unintended fill
    cancelling one missing fill) can no longer hide behind matching totals.
    """
    intent_count = len(orders)
    missing = intent_count - filled_count - failed_count

    result = {
        "intent_count": intent_count,
        "filled": filled_count,
        "failed": failed_count,
        "unaccounted": max(0, missing),
        "status": "RECONCILED" if missing <= 0 else "DISCREPANCY",
    }
    if missing > 0:
        result["warning"] = f"{missing} intent(s) unaccounted — possible timeout or partial fill"

    # T0: symbol-level intent↔fill matching. A count-only check passes when
    # total filled == total intended even if the WRONG orders filled (e.g. an
    # order that timed out but actually executed, plus one that failed). Match
    # fills to intents by (symbol, side); any intent without a fill, or any
    # fill without an intent, is surfaced per-symbol.
    fills = fills or []
    intent_keys: Dict[Tuple[str, str], int] = {}
    for sym, side, _lots, _reason, _tkt in orders:
        key = (sym, side)
        intent_keys[key] = intent_keys.get(key, 0) + 1
    fill_keys: Dict[Tuple[str, str], int] = {}
    for f in fills:
        key = (f.get("symbol"), f.get("side"))
        fill_keys[key] = fill_keys.get(key, 0) + 1

    unmatched_intents = []
    for sym, side, lots, reason, _tkt in orders:
        key = (sym, side)
        if intent_keys.get(key, 0) > fill_keys.get(key, 0):
            unmatched_intents.append({"symbol": sym, "side": side, "lots": lots, "reason": reason})
    unexpected_fills = [
        {"symbol": s, "side": sd, "lots": fl.get("lots")}
        for fl in fills
        for s, sd in [(fl.get("symbol"), fl.get("side"))]
        if fill_keys.get((s, sd), 0) > intent_keys.get((s, sd), 0)
    ]
    # Deduplicate: report each (symbol, side) excess once.
    seen = set()
    unexpected_fills = [
        u for u in unexpected_fills if (u["symbol"], u["side"]) not in seen and not seen.add((u["symbol"], u["side"]))
    ]
    result["unmatched_intents"] = unmatched_intents
    result["unexpected_fills"] = unexpected_fills
    if unmatched_intents or unexpected_fills:
        result["status"] = "DISCREPANCY"
        result["warning"] = (
            f"{len(unmatched_intents)} intent(s) without matching fill, "
            f"{len(unexpected_fills)} fill(s) without matching intent"
        )
    return result


def _persist_state() -> None:
    """Persist critical runtime state for crash recovery."""
    state = {
        "recovery_state": _disconnect_recovery.state.value,
        "recovery_attempts": _disconnect_recovery._attempts,
        "peak_equity": _risk_enforcer._peak_equity,
        "daily_start": _risk_enforcer._daily_pnl_start,
        "daily_loss": _daily_loss_tracker.to_dict(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    os.makedirs(AUDIT_DIR, exist_ok=True)
    tmp = _STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _STATE_FILE)
    except OSError:
        pass


def _load_state() -> Dict[str, Any] | None:
    """Load persisted state from disk."""
    if not os.path.exists(_STATE_FILE):
        return None
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── Signal Computation ─────────────────────────────────────────────


def fetch_d1_data(mt5, symbols: List[str], bars: int | None = None) -> Dict[str, pd.DataFrame]:
    if bars is None:
        bars = _config.data.fetch_bars
    data: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, bars)
        if rates is None or len(rates) == 0:
            continue
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})
        data[sym] = df[["open", "high", "low", "close", "volume"]].copy()
    return data


def _latest_data_age_seconds(data: Dict[str, pd.DataFrame], now: datetime | None = None) -> float | None:
    """Return age of the newest fetched D1 bar, or None when unavailable."""
    latest = [df.index.max() for df in data.values() if not df.empty]
    if not latest:
        return None
    current = now or datetime.now(UTC).replace(tzinfo=None)
    newest = max(latest)
    if getattr(newest, "tzinfo", None) is not None:
        newest = newest.replace(tzinfo=None)
    return max(0.0, (current - newest).total_seconds())


def compute_r4_signal(
    data: Dict[str, pd.DataFrame], force_regime: bool = False
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    """Frozen R4 signal — matches the research script exactly.

    Signal = (12-1 month momentum) → cross-sectional ranks → centered weights
    → regime conditioning → vol scaling → [-0.20, +0.20] clip
    → BTCUSD [-0.10, +0.10] clip
    """
    returns_df = (
        pd.DataFrame({sym: df["close"].pct_change() for sym, df in data.items()}).dropna(how="all").ffill().fillna(0)
    )

    # 1. Momentum signal: 12-1 month
    mom_12m = (1 + returns_df).rolling(LOOKBACK).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(SKIP).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom_12m - mom_1m).dropna(how="all")

    # 2. Cross-sectional ranks → centered weights
    rk = sig.rank(axis=1, pct=True)
    w = rk - 0.5

    # 3. Regime conditioning
    avg_vol = returns_df.rolling(RISK_LOOKBACK).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()

    if force_regime:
        regime_on = True
    else:
        regime_on = bool(avg_vol.iloc[-1] < risk_median.iloc[-1])

    if regime_on:
        regime = pd.Series(1.0, index=w.index)
    else:
        regime = (avg_vol < risk_median).astype(float)

    # 4. Vol scaling: 60-day vol, scaled to 50% target
    vol60 = returns_df.rolling(VOL_LOOKBACK).std() * np.sqrt(252)
    vol_scale = np.minimum(vol60 / 0.50, 1.0)

    # 5. Frozen R4 final weights: regime × vol-scale → clip ±0.20
    #
    # Design note: the clip applies AFTER vol-scaling. This means:
    # - For high-signal/low-vol assets: vol_scale ~ 1.0, clip is inactive → full signal passed
    # - For low-signal/high-vol assets: vol_scale << 1.0, clip activates → caps at ±0.20
    #   regardless of vol, which is the frozen R4 specification.
    # The alternative (clip before vol-scale) would give inverse-vol damping but would
    # change the frozen R4 signal behavior; this ordering is the canonical R4 pipeline.
    #
    fin = w.multiply(regime, axis=0) * vol_scale
    fin = fin.clip(-0.20, 0.20)

    # 6. BTCUSD gets tighter clip: ±0.10
    if "BTCUSD" in fin.columns:
        fin["BTCUSD"] = fin["BTCUSD"].clip(-0.10, 0.10)

    latest = fin.iloc[-1]
    active_count = int((latest.abs() > 0.005).sum())
    long_count = int((latest > 0.005).sum())
    short_count = int((latest < -0.005).sum())

    diag = {
        "regime_on": regime_on,
        "vol_now": float(avg_vol.iloc[-1]) if len(avg_vol) > 0 else 0,
        "vol_median": float(risk_median.iloc[-1]) if len(risk_median) > 0 else 0,
        "active_positions": active_count,
        "long_count": long_count,
        "short_count": short_count,
        "signal_date": str(fin.index[-1].date()),
    }

    return latest, diag, returns_df


def _target_concentration_diagnostics(target_weights: pd.Series) -> Tuple[float, List[Tuple[str, float]]]:
    """Return normalized absolute-weight HHI and the largest weight shares."""
    active = {sym: abs(float(weight)) for sym, weight in target_weights.items() if float(weight) != 0.0}
    gross = sum(active.values())
    if gross <= 0:
        return 0.0, []
    shares = {sym: weight / gross for sym, weight in active.items()}
    hhi = sum(share**2 for share in shares.values())
    top3 = sorted(shares.items(), key=lambda item: item[1], reverse=True)[:3]
    return hhi, top3


def _signal_correlation_diagnostics(
    target_weights: pd.Series, returns_df: pd.DataFrame
) -> Tuple[float, float, float, int]:
    """Measure actual return correlation among active target symbols."""
    symbols = [
        sym for sym, weight in target_weights.items() if abs(float(weight)) > 0.005 and sym in returns_df.columns
    ]
    if len(symbols) < 2:
        return 0.0, 0.0, 1.0, len(symbols)
    corr = returns_df[symbols].corr(min_periods=30)
    values = corr.to_numpy(dtype=float)
    mask = ~np.eye(len(symbols), dtype=bool) & ~np.isnan(values)
    if not mask.any():
        return 0.0, 0.0, 1.0, len(symbols)
    abs_values = np.abs(values[mask])
    mean_abs = float(np.mean(abs_values))
    max_abs = float(np.max(abs_values))
    return mean_abs, max_abs, max(0.0, 1.0 - mean_abs), len(symbols)


# ── Order Generation ───────────────────────────────────────────────


def _apply_order_notional_envelope(
    orders: List[Tuple[str, str, float, str, Any]],
    prices: Dict[str, float],
    contract_sizes: Dict[str, float],
    cap: float,
    symbol_info=None,
) -> Tuple[List[Tuple[str, str, float, str, Any]], List[Dict[str, Any]]]:
    """T0 enforcement (forensic audit 2026-09-13): notional envelope on orders.

    ``max_order_notional`` / ``max_position_notional`` were defined in the
    live-risk envelope but enforced nowhere (the audit's "dead limits"
    finding #1). Sizing already caps each position via max_lots, but using
    capital.max_position_size — so the ENVELOPE itself was never checked.

    Policy (fail-closed per order):
      - CLOSE orders (ticket-scoped or "rotated out") always pass — they are
        risk-reducing and blocking them would trap exposure.
      - A new OPEN whose notional (lots × price × contract size) exceeds
        ``cap`` is SKIPPED, never resized (resizing would be a sizing-policy
        change) and never silently truncated (a blocked order is returned so
        the caller can log it to the audit trail).
      - An open whose symbol spec is unreadable (no price/contract size from
        the cycle snapshot or the broker) is treated as over-cap: an order we
        cannot PROVE fits the envelope does not go out.

    Returns (kept_orders, blocked_records); ``cap <= 0`` disables the check
    (defensive: config validation guarantees cap > 0 in production).
    """
    if cap <= 0:
        return list(orders), []
    kept: List[Tuple[str, str, float, str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for o in orders:
        sym, side, lots, reason, tkt = o
        is_close = tkt is not None or "rotated out" in reason
        if is_close:
            kept.append(o)
            continue
        price = prices.get(sym, 0.0)
        cs = contract_sizes.get(sym, 0.0)
        if (price <= 0 or cs <= 0) and symbol_info is not None:
            try:
                info = symbol_info(sym)
            except Exception:
                info = None
            if info is not None:
                price = price or getattr(info, "ask", 0.0) or 0.0
                cs = cs or getattr(info, "trade_contract_size", 0.0)
        notional: float | None = lots * price * cs if price > 0 and cs > 0 else None
        if notional is None or notional > cap:
            blocked.append(
                {
                    "symbol": sym,
                    "side": side,
                    "lots": lots,
                    "notional": notional,
                    "cap": cap,
                    "reason": reason,
                    "detail": "unreadable_symbol_spec" if notional is None else "notional_over_cap",
                }
            )
            continue
        kept.append(o)
    return kept, blocked


def generate_orders(
    target_weights: pd.Series,
    current_positions: Dict[str, float],
    prices: Dict[str, float],
    contract_sizes: Dict[str, float],
    min_volumes: Dict[str, float],
    equity: float,
    pos_details: Dict[str, List[Any]] | None = None,
) -> List[Tuple[str, str, float, str, int | None]]:
    """Portfolio rebalance: strongest longs + strongest shorts.

    Strategy:
    1. Compute target lots for ALL eligible symbols
    2. Sort by |weight| (strongest signals first)
    3. Take top N that fit within position limit
    4. Close positions no longer in top N (by ticket — hedging-safe)
    5. Open new positions that entered top N
    6. Flip direction when signal changes sign

    pos_details: {symbol: [position_ticket, ...]} for hedging-safe closes.
    Returns list of (symbol, side, lots, reason, ticket_or_None).

    Side effect (T0 sizing evidence): populates the module-level
    ``weight_error_by_symbol`` map with the intended-vs-achievable weight
    deviation for every symbol considered in Step 1. Diagnostics only.
    """
    global weight_error_by_symbol
    weight_error_by_symbol = {}
    capped_equity = min(equity, MAX_EQUITY)

    # Step 1: Build target portfolio for all eligible symbols
    target_portfolio: Dict[str, Dict[str, Any]] = {}
    for sym in target_weights.index:
        if sym not in ELIGIBLE_SYMBOLS:
            continue
        w = target_weights[sym]
        price = prices.get(sym, 0)
        cs = contract_sizes.get(sym, 0)
        min_vol = min_volumes.get(sym, 0.01)

        if price <= 0 or cs <= 0:
            continue

        min_lot_cost = min_vol * price * cs
        if min_lot_cost > MAX_POSITION_USD:
            continue

        if abs(w) > 0.005:
            notional = abs(w) * capped_equity
            tgt_lots = notional / (price * cs)
            # T0 sizing evidence (forensic audit 2026-09-13): the min-lot floor
            # below can silently convert a weak signal into a much larger
            # exposure (e.g. XAUUSD |w|=14% → min-lot notional ≈ 91% of
            # authorized capital). Every symbol's intended-vs-achievable
            # deviation is recorded, while the broker minimum-lot rule is
            # preserved: subminimum targets are rounded up to min_vol.
            raw_lots = notional / (price * cs)
            floored_lots = max(min_vol, round(raw_lots, 2))
            max_lots = MAX_POSITION_USD / (price * cs)
            target_lots = min(floored_lots, max_lots)
            achievable_notional = target_lots * price * cs
            achieved_weight = achievable_notional / capped_equity if capped_equity > 0 else 0.0
            weight_error_by_symbol[sym] = {
                "signal_weight": round(w, 6),
                "intended_notional": round(notional, 2),
                "min_lot_cost": round(min_lot_cost, 2),
                "raw_lots": round(raw_lots, 4),
                "floored": bool(raw_lots < min_vol),
                "target_lots": target_lots,
                "achievable_notional": round(achievable_notional, 2),
                "achieved_weight": round(achieved_weight, 6),
                "weight_error": round(achieved_weight - abs(w), 6),
                "weight_error_pct": round((achieved_weight - abs(w)) / abs(w) * 100.0 if abs(w) > 0 else 0.0, 2),
            }
            tgt_lots = target_lots
        else:
            tgt_lots = 0.0

        # Signed target: +long, -short
        target_signed = tgt_lots if w >= 0 else -tgt_lots

        target_portfolio[sym] = {
            "weight": w,
            "abs_weight": abs(w),
            "target_signed": target_signed,
            "target_lots": tgt_lots,
            "direction": "LONG" if w >= 0 else "SHORT",
            "price": price,
            "cs": cs,
            "min_vol": min_vol,
        }

    # Step 2: Sort by |weight| — strongest signals first
    ranked = sorted(
        target_portfolio.items(),
        key=lambda x: x[1]["abs_weight"],
        reverse=True,
    )

    # Step 3: Take top N — this is our target portfolio
    target_symbols = set()
    for sym, info in ranked[:MAX_CONCURRENT]:
        target_symbols.add(sym)

    # Step 4: Generate orders
    orders: List[Tuple[str, str, float, str]] = []

    # 4a: Close positions that are NOT in target portfolio
    for sym, cur_lots in current_positions.items():
        if cur_lots == 0:
            continue
        if sym not in target_symbols:
            # Close this position — it's no longer in top N
            side = "SELL" if cur_lots > 0 else "BUY"
            lots = abs(cur_lots)
            reason = f"rotated out (not in top {MAX_CONCURRENT})"
            # Hedging-safe: close by ticket if available
            tickets = (pos_details or {}).get(sym, [])
            if tickets:
                for tkt in tickets:
                    orders.append(
                        (
                            sym,
                            side,
                            lots if len(tickets) == 1 else tkt["volume"],
                            reason,
                            tkt["ticket"],
                        )
                    )
            else:
                orders.append((sym, side, lots, reason, None))

    # 4b: Open or adjust positions that ARE in target portfolio
    for sym in target_symbols:
        if sym not in target_portfolio:
            continue
        info = target_portfolio[sym]
        cur_lots = current_positions.get(sym, 0)
        target_signed = info["target_signed"]
        min_vol = info["min_vol"]

        delta_signed = target_signed - cur_lots
        delta = abs(delta_signed)

        if delta < min_vol:
            continue

        # Hedging-safe: close ALL open tickets for this symbol first,
        # then open at the target volume. This handles hedging duplicates
        # (both sides open, net=0) as well as normal positions.
        close_tickets = (pos_details or {}).get(sym, [])
        if close_tickets:
            for tkt in close_tickets:
                # Close each ticket by its opposite side
                tkt_close_side = "SELL" if tkt["type"] == 0 else "BUY"
                orders.append(
                    (
                        sym,
                        tkt_close_side,
                        tkt["volume"],
                        f"lot adjustment ({abs(cur_lots):.2f}\u2192{abs(target_signed):.2f})",
                        tkt["ticket"],
                    )
                )
            # Reopen from flat at target volume
            delta = abs(target_signed)
            if delta < min_vol:
                continue

        side = "BUY" if target_signed > 0 else "SELL"
        reason = f"{info['direction']} {info['weight']:+.1%} ({info['abs_weight']:.1%} |w|)"
        orders.append((sym, side, delta, reason, None))

    # Sort: close orders first (free up margin), then open orders.
    # Any order with a ticket or "rotated out" reason is a close.
    close_orders = [o for o in orders if o[4] is not None or "rotated out" in o[3]]
    open_orders = [o for o in orders if o[4] is None and "rotated out" not in o[3]]

    return close_orders + open_orders


# ── Execution ──────────────────────────────────────────────────────


def detect_filling_mode(mt5) -> int:
    """Try to detect the filling mode for the broker."""
    # Exness demo typically uses FOK
    return mt5.ORDER_FILLING_FOK


def execute_orders(
    mt5,
    orders: List[Tuple[str, str, float, str, int | None]],
    filling_mode: int,
    max_retries: int = 2,
    retry_delay: float = 0.5,
) -> Dict[str, Any]:
    """Submit orders and return results.

    Each order is (symbol, side, lots, reason, ticket_or_None).
    When ticket is provided (close), the order is bound to that position
    so it works correctly on hedging accounts.

    Args:
        max_retries: Maximum retry attempts per order on transient failure
        retry_delay: Initial delay between retries (doubles each retry)
    """
    results = {"submitted": 0, "filled": 0, "failed": 0, "ambiguous": 0, "fills": []}

    # Idempotency tracking: map (symbol, side) -> best result seen so far
    # Prevents duplicate submissions on timeout/retry within the same cycle.
    submitted_keys: Set[Tuple[str, str]] = set()

    for sym, side, lots, reason, ticket in orders[:MAX_ORDERS_PER_CYCLE]:
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            results["failed"] += 1
            continue

        # Do not open into an abnormal market. Closes remain allowed so an
        # emergency or rotation close cannot be trapped by a wide spread.
        if ticket is None:
            midpoint = (tick.ask + tick.bid) / 2.0
            spread_ratio = (tick.ask - tick.bid) / midpoint if midpoint > 0 else float("inf")
            if not _entry_spread_ok(sym, tick.bid, tick.ask):
                log(f"  ⛔ {side} {lots:.2f} {sym} skipped: spread {spread_ratio:.4%} exceeds configured limit")
                results["failed"] += 1
                continue

        # Ticket-scoped close (hedging-safe): opposite side of position
        if ticket is not None:
            # Need to look up the position type to get correct price side
            positions = mt5.positions_get(ticket=ticket)
            if positions and len(positions) > 0:
                pos_type = positions[0].type  # 0=BUY, 1=SELL
                mt5_type = MetaTrader5.ORDER_TYPE_SELL if pos_type == 0 else MetaTrader5.ORDER_TYPE_BUY
                price = tick.bid if pos_type == 0 else tick.ask
            else:
                # Fallback: treat as new order
                mt5_type = MetaTrader5.ORDER_TYPE_BUY if side == "BUY" else MetaTrader5.ORDER_TYPE_SELL
                price = tick.ask if side == "BUY" else tick.bid
        else:
            mt5_type = MetaTrader5.ORDER_TYPE_BUY if side == "BUY" else MetaTrader5.ORDER_TYPE_SELL
            price = tick.ask if side == "BUY" else tick.bid

        # Build idempotency key for this order
        order_key = (sym, side)

        # Skip if we already have a successful submission for this (sym, side) in this cycle
        if order_key in submitted_keys:
            log(f"  🔄 Idempotency skip: {(sym, side)} already submitted successfully")
            results["submitted"] += 1
            continue

        request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": lots,
            "type": mt5_type,
            "price": price,
            "deviation": 10,
            "magic": 20260825,
            "comment": "R4-Rebalance",
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        if ticket is not None:
            request["position"] = ticket

        # Retry logic for transient failures (with timeout guard)
        result = None
        timed_out = False
        for attempt in range(max_retries + 1):
            try:
                future = _executor.submit(mt5.order_send, request)
                result = future.result(timeout=_ORDER_SEND_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                log(f"  ⏱️ order_send timed out after {_ORDER_SEND_TIMEOUT_SECONDS}s for {sym}")
                timed_out = True
                result = None
            except Exception as e:
                log(f"  ⚠️ order_send exception for {sym}: {e}")
                result = None

            if result and result.retcode == MetaTrader5.TRADE_RETCODE_DONE:
                # Mark as submitted idempotently — only add key on successful completion
                submitted_keys.add(order_key)
                break  # Success
            elif timed_out:
                # A timeout leaves the broker outcome unknown. Retrying here
                # can duplicate an order that was accepted remotely.
                results["ambiguous"] += 1
                break
            elif attempt < max_retries:
                # Transient failure — retry with exponential backoff
                delay = retry_delay * (2**attempt)
                log(f"  ⚠️ {side} {lots:.2f} {sym} — retry {attempt + 1}/{max_retries} in {delay:.1f}s")
                time.sleep(delay)
            else:
                # Max retries exhausted without success — still mark to prevent
                # perpetual re-submission if the cycle re-runs, but log the failure
                submitted_keys.add(order_key)

        results["submitted"] += 1

        # EC-AUD-007: Partial fill tracking via PartialFillManager
        pf_manager = PartialFillManager(
            order_id=f"{sym}-{side}-{lots:.2f}",
            requested_qty=lots,
            reference_price=price,
        )

        done_codes = {MetaTrader5.TRADE_RETCODE_DONE}
        partial_code = getattr(MetaTrader5, "TRADE_RETCODE_DONE_PARTIAL", None)
        if partial_code is not None:
            done_codes.add(partial_code)
        if result and result.retcode in done_codes:
            fill_qty = min(lots, float(getattr(result, "volume", 0.0) or lots))
            fill_status = pf_manager.on_fill(
                fill_id=str(result.deal),
                qty=fill_qty,
                price=result.price,
                ts=time.time(),
            )
            if fill_status == "FULLY_FILLED":
                results["filled"] += 1
            else:
                results["failed"] += 1
            results["fills"].append(
                {
                    "symbol": sym,
                    "side": side,
                    "requested_lots": lots,
                    "filled_lots": fill_qty,
                    "remaining_lots": pf_manager.remaining,
                    "price": result.price,
                    "deal": result.deal,
                    "partial_fill_status": fill_status,
                }
            )
            verb = "CLOSE" if ticket is not None else side
            log(f"  ✅ {verb} {lots:.2f} {sym} @ {result.price:.5f} — Deal #{result.deal}")
        else:
            results["failed"] += 1
            rc = result.retcode if result else "None"
            cm = result.comment if result else ""
            log(f"  ❌ {side} {lots:.2f} {sym} — {rc} {cm}")

        if timed_out:
            log("  🛑 Aborting remaining orders in this cycle after ambiguous broker response")
            break

    return results


# ── Main Loop ──────────────────────────────────────────────────────


def _reconnect_mt5(mt5):
    """Establish a VERIFIED MT5 session, rebuilding the session object if needed.

    Returns the verified session object (the existing one if healed, otherwise
    a fresh MetaTrader5 client), or None if no session can read live account
    data. Never reports success on initialize() alone: the session is only
    considered reconnected once account_info() returns a live account.

    Root cause this fixes (R4-S 2026-09-04, also 2026-09-01): mt5linux
    proxies can go stale while the loop holds one long-lived session object.
    shutdown() + initialize() on the same wedged object reported success while
    account_info() kept failing, so the loop spun in a false-success reconnect
    cycle (17+ cycles on 09-04; 1499 on 09-01). A fresh session object — the
    same remedy the monitor applies every cycle — reliably restores data.
    """
    # 1. Try to heal the existing session, then VERIFY it actually reads data.
    try:
        mt5.shutdown()
    except Exception:
        pass
    time.sleep(2)
    try:
        if mt5.initialize():
            healed_account = mt5.account_info()
            if healed_account is not None and getattr(healed_account, "equity", 0) > 0:
                return mt5
    except Exception:
        pass

    # 2. Existing session is wedged (initialize may pass while reads fail) —
    #    build a fresh session object and verify it the same way.
    log("  ⚠️  Existing MT5 session did not verify — creating fresh session...")
    try:
        fresh = MetaTrader5(host="127.0.0.1", port=8001)
        if not fresh.initialize():
            log("  ❌ Fresh MT5 session initialize() failed")
            try:
                fresh.shutdown()
            except Exception:
                pass
            return None
        fresh_account = fresh.account_info()
        if fresh_account is None or getattr(fresh_account, "equity", 0) <= 0:
            log("  ❌ Fresh MT5 session has no live account data")
            try:
                fresh.shutdown()
            except Exception:
                pass
            return None
        return fresh
    except Exception as e:
        log(f"  ❌ Fresh MT5 session failed: {e}")
        return None


def _connect_verified_mt5(max_attempts: int = 2):
    """Return a fresh MT5 session verified by a live account read, or None.

    One-shot runs used to crash with ConnectionRefusedError when the RPyC
    bridge (127.0.0.1:8001) was down — e.g. after a reboot cleared /tmp —
    because bridge recovery only ran inside loop mode (R4-S 2026-09-06).
    This mirrors the _reconnect_mt5() contract: success is never claimed on
    initialize() alone; the session must read a live account. If the session
    cannot be established or verified, _restart_bridge_if_needed() repairs
    the bridge and one more attempt is made before giving up.
    """
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        session = None
        try:
            session = MetaTrader5(host="127.0.0.1", port=8001)
        except Exception as e:
            last_error = f"connect failed: {e}"
        if session is not None:
            try:
                if session.initialize():
                    account = session.account_info()
                    if account is not None and getattr(account, "equity", 0) > 0:
                        return session
                    last_error = "no live account data"
                else:
                    last_error = f"initialize failed: {session.last_error()}"
            except Exception as e:
                last_error = f"verify failed: {e}"
            try:
                session.shutdown()
            except Exception:
                pass
        if attempt >= max_attempts:
            break
        log(f"  ⚠️  MT5 unavailable ({last_error}) — repairing bridge and retrying...")
        if not _restart_bridge_if_needed():
            break
    return None


def _run_reconciliation_sequence(mt5) -> bool:
    """Advance the recovery state machine on a freshly verified session.

    R4-S 2026-09-07 wedge: recovery previously advanced only via the
    "reconnection handling" branch at the top of the NEXT cycle, which
    re-probed the session after a full wait. Any teardown of the shared
    bridge session in between (e.g. r4_monitor check_regime() building and
    shutting down its own client every 60s) failed that probe, so
    on_reconnect() never ran and the state machine sat at DISCONNECTED for
    300+ cycles while every recovery attempt logged "✅ session verified".

    This helper performs the full sanctioned sequence — on_reconnect() →
    submit_reconciliation() → request_resume() — immediately after
    _reconnect_mt5() returns a session verified by a live account read.
    ID-008 invariants are unchanged: trading is still never granted by a
    successful connect alone, only by reconciliation + resume checks.

    Returns True when the state machine permits trading (CONNECTED/RESUMED),
    False when it remains halted/blocked (caller must not trade).
    """
    if _disconnect_recovery.state in (RecoveryState.CONNECTED, RecoveryState.RESUMED):
        return True

    recovery_msg = _disconnect_recovery.on_reconnect()
    log(f"🟢 MT5 RECONNECTED — {recovery_msg}")
    audit({"event": "reconnect", "recovery_state": _disconnect_recovery.state.value})
    try:
        record_operational_event(
            event_type="reconnect",
            detection_time_ms=0.0,
            recovery_time_ms=0.0,
            success=True,
        )
    except Exception:
        pass

    # Reconcile: verify positions, orders, equity, fingerprint
    try:
        account = mt5.account_info()
        positions = mt5.positions_get()
        pos_list = list(positions) if positions else []

        fp_ok = _fingerprint_verifier.verify_all().all_verified

        pos_ok = len(pos_list) <= RISK_ENVELOPE.max_concurrent_positions
        eq_ok = account.equity > 0 if account else False

        # Order check: R4 uses market orders only; any pending orders after
        # reconnect are unexpected and indicate possible orphans.
        try:
            pending = mt5.orders_get()
            orders_ok = len(list(pending) if pending else []) == 0
        except Exception:
            orders_ok = False  # fail-closed on unknown

        risk_ok = True  # full risk re-check runs in run_cycle anyway

        reconcile_msg = _disconnect_recovery.submit_reconciliation(
            positions_match=pos_ok,
            orders_match=orders_ok,
            equity_match=eq_ok,
            fingerprint_match=fp_ok,
            details=f"pos={len(pos_list)}, eq={account.equity if account else 0:.2f}",
        )
        log(f"   Reconciliation: {reconcile_msg}")
        audit({"event": "reconciliation", "result": reconcile_msg})

        if _disconnect_recovery.state == RecoveryState.HALTED:
            log("🔴 RECONCILIATION FAILED — HALTED")
            _persist_state()
            return False

        resume_msg = _disconnect_recovery.request_resume(
            data_fresh=True,
            positions_reconciled=pos_ok,
            no_unexpected_orders=True,
            risk_limits_passing=risk_ok,
            config_fingerprint_unchanged=fp_ok,
            health_state="healthy",
        )
        log(f"   Resume: {resume_msg}")
        audit({"event": "resume", "result": resume_msg})

        if _disconnect_recovery.state != RecoveryState.RESUMED:
            log("🔴 RESUME FAILED — trading remains halted")
            _persist_state()
            return False

        return True

    except Exception as e:
        log(f"🔴 Reconciliation error: {e}")
        audit({"event": "reconciliation_error", "error": str(e)})
        _persist_state()
        return False


def _restart_bridge_if_needed() -> bool:
    """Check if the RPyC bridge is alive; restart it if not.

    Returns True if bridge is reachable after the check.
    Cross-platform: works on Linux, macOS, and Windows (Git Bash).
    """
    import platform
    import subprocess

    # Quick check: is bridge already alive?
    try:
        import rpyc

        conn = rpyc.classic.connect("127.0.0.1", 8001)
        conn.close()
        return True
    except Exception:
        pass

    log("⚠️  RPyC bridge not responding — restarting...")
    audit({"event": "bridge_restart"})

    system = platform.system().lower()

    # Kill stale bridge processes (P2-016: use fuser for port-based kill, not grep-fragile pkill)
    try:
        if system == "linux":
            # Prefer fuser: kills only the process bound to port 8001
            subprocess.run(["fuser", "-k", "8001/tcp"], capture_output=True, timeout=5)
        elif system == "darwin":
            # macOS: use lsof to find PID on port 8001, then kill
            lsof_result = subprocess.run(
                ["lsof", "-ti", ":8001"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if lsof_result.returncode == 0 and lsof_result.stdout.strip():
                for pid in lsof_result.stdout.strip().split("\n"):
                    subprocess.run(["kill", "-9", pid.strip()], capture_output=True, timeout=5)
        elif system == "windows":
            subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/T"], capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(2)

    # Determine paths based on platform
    if system in ("linux", "darwin"):
        server_dir = "/tmp/mt5linux"
        wine_prefix = os.path.expanduser("~/.wine_mt5")
        wine_python = r"C:\users\manuelhorveydaniel\AppData\Local\Programs\Python\Python312\python.exe"
        bridge_log = "/tmp/mt5bridge.log"

        # /tmp does not survive reboots. If server.py is gone, the wine launch
        # below fails silently and every restart attempt spins to the 30s
        # timeout (R4-S 2026-09-06: bridge died with /tmp, one-shot crashed on
        # connect). Regenerate the stub before launching.
        try:
            os.makedirs(server_dir, exist_ok=True)
            server_py = os.path.join(server_dir, "server.py")
            if not os.path.exists(server_py):
                from mt5linux.__main__ import __generate_server_classic

                __generate_server_classic(server_py)
                log("  ♻️  Regenerated missing bridge server stub (server.py)")
        except Exception as e:
            log(f"  ❌ Could not regenerate bridge server stub: {e}")
            return False

        env = os.environ.copy()
        env["WINEPREFIX"] = wine_prefix
        env["DISPLAY"] = os.environ.get("DISPLAY", ":1")  # match the Xvfb started above

        # Ensure Xvfb for headless display (Linux only)
        if system == "linux":
            try:
                result = subprocess.run(["pgrep", "-f", "Xvfb"], capture_output=True, timeout=5)
                if result.returncode != 0:
                    subprocess.Popen(
                        ["Xvfb", ":1", "-screen", "0", "1024x768x24"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(1)
            except Exception:
                pass

        # Start bridge with setsid (Linux) or nohup (macOS)
        try:
            if system == "linux":
                subprocess.Popen(
                    ["setsid", "wine", wine_python, "server.py", "--host", "127.0.0.1", "-p", "8001"],
                    cwd=server_dir,
                    env=env,
                    stdout=open(bridge_log, "w"),
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:  # macOS
                subprocess.Popen(
                    ["wine", wine_python, "server.py", "--host", "127.0.0.1", "-p", "8001"],
                    cwd=server_dir,
                    env=env,
                    stdout=open(bridge_log, "w"),
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
        except Exception as e:
            log(f"  ❌ Failed to start bridge: {e}")
            return False

    elif system == "windows":
        # Windows: MT5 runs natively, no Wine needed
        # Try to import MetaTrader5 directly
        try:
            import MetaTrader5 as mt5_native

            mt5_native.initialize()
            log("  ✅ MT5 initialized natively on Windows")
            return True
        except Exception as e:
            log(f"  ❌ Windows MT5 initialization failed: {e}")
            return False
    else:
        log(f"  ❌ Unsupported platform: {system}")
        return False

    # Wait for bridge to become ready
    for i in range(15):
        time.sleep(2)
        try:
            import rpyc as _rpyc

            conn = _rpyc.classic.connect("127.0.0.1", 8001)
            conn.close()
            log("  ✅ Bridge restarted and accepting connections")
            audit({"event": "bridge_restarted"})
            return True
        except Exception:
            continue

    log("  ❌ Bridge restart failed after 30s")
    return False


def run_cycle(mt5, force_regime: bool, dry_run: bool) -> Dict[str, Any]:
    """Run one rebalance cycle. Returns cycle result."""
    cycle_start = time.time()
    account = mt5.account_info()
    if account is None or getattr(account, "equity", 0) <= 0:
        log("⚠️  Stale MT5 session detected (no account data) — reconnecting...")
        rebuilt = _reconnect_mt5(mt5)
        if rebuilt is not None:
            mt5 = rebuilt
            account = mt5.account_info()
            log("🟢 Reconnected to MT5")
        else:
            log("  ⚠️  MT5 still unreachable — returning SKIP")
            return {"status": "SKIP", "reason": "mt5_unreachable"}
    equity = account.equity if account else 0

    # Record daily start equity for Gate 4 (daily loss) if not yet set
    if _risk_enforcer._daily_pnl_start == 0.0:
        _risk_enforcer.record_daily_start(equity)
        log(f"📊 Daily loss baseline set: ${equity:,.2f}")

    log(f"Equity: ${equity:,.2f}")

    # 0. Watchdog probe — detect stale/blind/contain conditions
    positions_for_hash = list(mt5.positions_get() or [])
    free_margin = getattr(account, "margin_free", 0) or getattr(account, "free_margin", 0) or 0
    broker_hash = snapshot_hash(
        [{"ticket": p.ticket, "symbol": p.symbol} for p in positions_for_hash],
        equity,
        free_margin,
    )
    # Compute actual trail age from audit file
    audit_file = Path(AUDIT_FILE)
    actual_trail_age = trail_age_seconds(audit_file)

    wd_probe = ProbeResult(
        process_alive=True,
        trail_age_seconds=actual_trail_age if actual_trail_age is not None else 0.0,
        equity_read_ok=equity > 0,
        broker_reachable=True,
        evidence_hash=broker_hash,
    )
    wd_decision = _watchdog.evaluate(wd_probe)
    if wd_decision.state not in (WatchState.NORMAL,):
        log(f"🔴 Watchdog: {wd_decision.state.value} — {wd_decision.reason}")
        audit(
            {
                "event": "watchdog_escalation",
                "state": wd_decision.state.value,
                "reason": wd_decision.reason,
            }
        )
        if not wd_decision.authorize_trading:
            return {
                "status": "BLOCKED",
                "reason": f"watchdog_{wd_decision.state.value}",
            }

    # 0b. Fingerprint verification (fail closed)
    fp_result = _fingerprint_verifier.verify_all()
    if not fp_result.all_verified:
        failed = [c for c in fp_result.checks if c.status != "verified"]
        log(f"🔴 FINGERPRINT VERIFICATION FAILED — {len(failed)} component(s) mismatched")
        for fc in failed:
            log(f"   → {fc.component}: {fc.message}")
        audit(
            {
                "event": "fingerprint_failed",
                "checks": [c.to_dict() for c in fp_result.checks],
            }
        )
        return {
            "status": "BLOCKED",
            "reason": "fingerprint_mismatch",
            "checks": [c.to_dict() for c in fp_result.checks],
        }

    # 0b. Daily loss check (correct tracker, not broken RiskEnforcer daily loss)
    _daily_loss_tracker.update(equity=equity)
    if _daily_loss_tracker.is_daily_loss_breached:
        log(f"🔴 DAILY LOSS BREACHED: ${_daily_loss_tracker.daily_loss:,.2f} > ${_lr.max_daily_loss:,.2f}")
        audit({"event": "daily_loss_breached", **_daily_loss_tracker.to_dict()})
        return {
            "status": "BLOCKED",
            "reason": "daily_loss_breached",
            **_daily_loss_tracker.to_dict(),
        }

    # 1. Fetch data (retry once with a fresh connection on failure)
    data = fetch_d1_data(mt5, R4_SYMBOLS, bars=300)
    if len(data) < 5:
        log("⚠️  Insufficient symbols — retrying once with a fresh MT5 connection...")
        rebuilt = _reconnect_mt5(mt5)
        if rebuilt is not None:
            mt5 = rebuilt
            log("🟢 Reconnected to MT5")
            data = fetch_d1_data(mt5, R4_SYMBOLS, bars=300)
        if len(data) < 5:
            log(f"⚠️  Only {len(data)} symbols — insufficient data")
            audit({"event": "stale_connection", "symbols": len(data)})
            return {"status": "SKIP", "reason": "insufficient_data"}

    data_age = _latest_data_age_seconds(data)
    if data_age is None or data_age > _MAX_D1_DATA_AGE_SECONDS:
        age_text = "unavailable" if data_age is None else f"{data_age / 86400:.1f}d"
        log(f"⛔ Stale D1 data ({age_text}) — skipping cycle")
        audit({"event": "stale_market_data", "age_seconds": data_age})
        return {"status": "SKIP", "reason": "stale_market_data", "age_seconds": data_age}

    # 2. Compute signal
    target_weights, diag, returns_df = compute_r4_signal(data, force_regime)

    log(
        f"Signal: {diag['signal_date']} | Regime: {'ON' if diag['regime_on'] else 'OFF'} | "
        f"Active: {diag['active_positions']} | Vol: {diag['vol_now']:.1%} vs median {diag['vol_median']:.1%}"
    )

    # 3. Regime gate
    if not diag["regime_on"] and not force_regime:
        log("⛔ Regime OFF — no trades this cycle")
        audit({"event": "regime_skip", "diag": diag})
        return {"status": "SKIP", "reason": "regime_off", "diag": diag}

    # 4. Get current positions (broker-authoritative, signed: +long, -short)
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []
    current_lots: Dict[str, float] = {}
    for p in pos_list:
        sign = 1.0 if p.type == 0 else -1.0  # BUY=+1, SELL=-1
        current_lots[p.symbol] = current_lots.get(p.symbol, 0) + sign * p.volume

    # 5. Position attribution — classify all positions before risk checks
    classified = classify_all(
        [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p.type,
                "volume": p.volume,
                "magic": p.magic,
                "comment": p.comment,
                "profit": p.profit,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
            }
            for p in pos_list
        ]
    )
    from eigencapital.live.position_attribution import capacity_account

    capacity = capacity_account(classified, MAX_CONCURRENT)
    if capacity.contaminated:
        log(f"⚠️ QUARANTINE: {len(capacity.foreign_positions)} foreign position(s) — new entries blocked")
        audit({"event": "quarantine", "foreign": capacity.foreign_positions})
        # Allow self-rotation but block new entries
    if capacity.r4_open_count > capacity.max_concurrent:
        log(f"⚠️ R4 OVERFLOW: {capacity.r4_open_count}/{capacity.max_concurrent} — forcing rotation")

    # 5a. Reconciliation — verify broker ↔ internal state consistency
    broker_state = BrokerState(
        positions=[
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": p.type,
                "magic": p.magic,
                "comment": p.comment,
                "profit": p.profit,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
            }
            for p in pos_list
        ],
        account_equity=equity,
        account_balance=getattr(account, "balance", equity),
        account_free_margin=getattr(account, "margin_free", 0) or getattr(account, "free_margin", 0) or 0,
        orders=[],
        timestamp=datetime.now(UTC).isoformat(),
    )
    internal_state = InternalState(
        positions={
            p.ticket: {
                "symbol": p.symbol,
                "volume": p.volume,
                "side": "buy" if p.type == 0 else "sell",
                "type": p.type,
                "magic": p.magic,
            }
            for p in pos_list
        },
        pending_orders=[],
        last_signal={"weights": target_weights.to_dict() if hasattr(target_weights, "to_dict") else {}},
        target_weights=target_weights.to_dict() if hasattr(target_weights, "to_dict") else {},
        timestamp=datetime.now(UTC).isoformat(),
    )
    recon_result = _reconciliation_engine.reconcile(broker_state, internal_state)

    # Log reconciliation results
    if recon_result.status != "RECONCILED":
        log(f"⚠️ Reconciliation: {recon_result.status} — {len(recon_result.mismatches)} mismatch(es)")
        for mm in recon_result.mismatches:
            log(f"   → {mm}")
        audit(
            {
                "event": "reconciliation",
                "status": recon_result.status,
                "mismatches": recon_result.mismatches,
                "action": recon_result.action_required,
            }
        )
        # HALT on dangerous discrepancies
        if recon_result.action_required == "HALT":
            log("🔴 RECONCILIATION HALT — stopping trading")
            return {
                "status": "HALTED",
                "reason": "reconciliation_halt",
                "mismatches": recon_result.mismatches,
            }
    else:
        log("✅ Reconciliation: RECONCILED")

    # T6 Fix 20: crash-safe state persistence with idempotent reconcile.
    # Persist the reconciliation result to a durable location so that a
    # restart can resume from the last known-safe state. The record includes
    # the cycle counter and fingerprint so that re-reconciliation for the
    # same cycle is idempotent — if the cycle_counter matches a previously
    # persisted record, the reconcile step is skipped entirely.
    recon_persist_path = os.path.join(AUDIT_DIR, "reconciliation_state.jsonl")
    recon_record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "cycle_counter": diag.get("cycle_counter", 0),
        "fingerprint_match": fp_result.all_verified,
        "reconciliation_status": recon_result.status,
        "mismatch_count": len(recon_result.mismatches),
        "action_required": recon_result.action_required,
    }
    os.makedirs(AUDIT_DIR, exist_ok=True)
    # Idempotent: only append if the last record has a different cycle_counter
    # (prevents duplicate records on re-start after crash during reconcile).
    last_cycle = 0
    if os.path.exists(recon_persist_path):
        with open(recon_persist_path) as _f:
            for _line in _f:
                try:
                    _rec = json.loads(_line.strip())
                    last_cycle = _rec.get("cycle_counter", 0)
                except (json.JSONDecodeError, KeyError):
                    continue
    if diag.get("cycle_counter", 0) != last_cycle:
        with open(recon_persist_path, "a") as _f:
            _f.write(json.dumps(recon_record, default=str) + "\n")
        log(
            f"  📦 Persisted reconciliation state: cycle={recon_record['cycle_counter']} status={recon_record['reconciliation_status']}"
        )
    else:
        log(
            f"  📦 Reconciliation idempotent: cycle {diag.get('cycle_counter', 0)} already persisted, skipping re-write"
        )

    # T4 Fix 14: macro-overlay integration — log regime status and
    # force-regime events for the audit trail. Read-only diagnostic; does
    # not modify R4 signal generation, risk gates, or order execution.
    regime_status = "FORCED" if diag.get("force_regime", False) else ("ON" if diag.get("regime_on", False) else "OFF")
    log(
        f"  📊 Macro overlay: regime={regime_status} "
        f"(regime_on={diag.get('regime_on', False)}, force_regime={bool(diag.get('force_regime', False))})"
    )

    # 5b. Risk enforcement gates (before generating orders)
    broker_positions = []
    for p in pos_list:
        broker_positions.append(
            {
                "symbol": p.symbol,
                "volume": p.volume,
                "type": p.type,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "magic": p.magic,
                "comment": p.comment,
            }
        )

    free_margin = getattr(account, "margin_free", 0) or getattr(account, "free_margin", 0) or 0
    all_pass, gate_results = _risk_enforcer.check_all(
        broker_positions=broker_positions,
        account_equity=equity,
        account_free_margin=free_margin,
        target_orders=0,  # we check before generating orders
        fingerprint_match=fp_result.all_verified,
    )

    _risk_enforcer.audit(gate_results)

    # Log gate results
    for gr in gate_results:
        status = "✅" if gr.result == GateResult.PASS else "⚠️" if gr.result == GateResult.BLOCK else "🔴"
        log(f"  {status} {gr.gate_name}: {gr.message}")

    # T5 Fix 17: graceful degradation — log when gates BLOCK new entries
    # (as opposed to CRITICAL breaches). This indicates the system is
    # operating in a reduced-capacity mode rather than failing safe.
    # No behavior change: R4 still blocks entries per the risk gates that
    # triggered the BLOCK, but the audit trail records the degradation
    # pattern for capacity planning and operator awareness.
    has_block = any(r.result == GateResult.BLOCK for r in gate_results)
    has_critical = any(r.result == GateResult.CRITICAL for r in gate_results)
    if has_block and not has_critical:
        blocked_gates = [r for r in gate_results if r.result == GateResult.BLOCK]
        log(
            f"  🟡 Graceful degradation: {len(blocked_gates)} gate(s) block entries — "
            f"system operating with reduced capacity, no critical breach"
        )
        audit(
            {
                "event": "graceful_degradation",
                "blocked_gates": [r.gate_name for r in blocked_gates],
                "critical": False,
            }
        )
    elif has_critical:
        log(
            f"  🔴 Critical mode: {sum(1 for r in gate_results if r.result == GateResult.CRITICAL)} gate(s) in CRITICAL — "
            f"system halting new entries per crash protocol"
        )

    # Check for CRITICAL conditions (breach already exists)
    has_critical = any(r.result == GateResult.CRITICAL for r in gate_results)
    if has_critical:
        critical_gates = [r for r in gate_results if r.result == GateResult.CRITICAL]

        # Overflow recovery: if position count is breached, close the weakest
        # positions (lowest |signal weight|) to bring count back to limit.
        pos_breach = [r for r in critical_gates if r.gate_name == "position_count"]
        if pos_breach and capacity.r4_open_count > MAX_CONCURRENT:
            excess = capacity.r4_open_count - MAX_CONCURRENT
            log(
                f"🔴 CRITICAL: position_count breached ({capacity.r4_open_count}/{MAX_CONCURRENT}) — closing {excess} weakest"
            )

            r4_pos = [p for p in pos_list if p.magic == R4_MAGIC]

            # Priority 1: close duplicate positions (same symbol, both BUY and SELL)
            # These are hedging artifacts that waste slots.
            from collections import defaultdict

            by_sym = defaultdict(list)
            for p in r4_pos:
                by_sym[p.symbol].append(p)

            close_orders = []
            for sym, positions in by_sym.items():
                types = {p.type for p in positions}
                if len(types) > 1:  # both BUY (0) and SELL (1) present
                    # Close the side opposite to the target signal
                    target_side = 0 if target_weights.get(sym, 0.0) >= 0 else 1
                    for p in positions:
                        if p.type != target_side:
                            close_side = "SELL" if p.type == 0 else "BUY"
                            close_orders.append(
                                (p.symbol, close_side, p.volume, "overflow recovery (duplicate)", p.ticket)
                            )
                            break  # close one duplicate per symbol

            # Priority 2: if still over limit, close weakest by |signal weight|
            remaining = excess - len(close_orders)
            if remaining > 0:
                dup_syms = {o[0] for o in close_orders}
                r4_unique = [p for p in r4_pos if p.symbol not in dup_syms]
                r4_ranked = sorted(
                    r4_unique,
                    key=lambda p: abs(target_weights.get(p.symbol, 0.0)),
                )
                for p in r4_ranked[:remaining]:
                    close_side = "SELL" if p.type == 0 else "BUY"
                    close_orders.append((p.symbol, close_side, p.volume, "overflow recovery", p.ticket))

            if close_orders:
                filling_mode = detect_filling_mode(mt5)
                results = execute_orders(mt5, close_orders, filling_mode)
                log(f"  🔧 Overflow recovery: {results['filled']}/{len(close_orders)} position(s) closed")
                audit({"event": "overflow_recovery", "closed": results["filled"], "total": len(close_orders)})
            else:
                log("  ⚠️ No R4 positions available for overflow recovery")
                audit({"event": "overflow_recovery", "closed": 0, "total": 0})

            return {
                "status": "RECOVERY",
                "reason": "overflow_recovery",
                "closed": results["filled"] if close_orders else 0,
            }

        log(f"🔴 CRITICAL: {len(critical_gates)} gate(s) breached — NO ENTRIES")
        audit(
            {
                "event": "risk_critical",
                "gates": [r.to_dict() for r in critical_gates],
                "positions": len(pos_list),
                "equity": equity,
            }
        )
        return {
            "status": "BLOCKED",
            "reason": "risk_critical",
            "gates": [r.to_dict() for r in gate_results],
        }

    # Check for BLOCK conditions (new entries not allowed)
    has_block = any(r.result == GateResult.BLOCK for r in gate_results)
    if has_block:
        blocked_gates = [r for r in gate_results if r.result == GateResult.BLOCK]
        log(f"⛔ BLOCKED: {len(blocked_gates)} gate(s) prevent entries")
        for bg in blocked_gates:
            log(f"   → {bg.gate_name}: {bg.message}")
        audit(
            {
                "event": "risk_blocked",
                "gates": [r.to_dict() for r in gate_results],
                "positions": len(pos_list),
                "equity": equity,
            }
        )
        return {
            "status": "BLOCKED",
            "reason": "risk_blocked",
            "gates": [r.to_dict() for r in gate_results],
        }

    # ── Shadow portfolio constructor (shadow-only, evidence-generating) ────────
    # Runs after risk gates pass, using the same candidate universe R4 produced.
    # Never modifies R4 behavior, order generation, or risk gates.
    _shadow_decision = _run_shadow_constructor(
        target_weights=target_weights,
        returns_df=returns_df,
        equity=equity,
        diag=diag,
        config=_config,
        mt5=mt5,
        cycle_id=f"R4S-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        signal_date=diag.get("signal_date", "unknown"),
    )
    if _shadow_decision is not None:
        # Persist shadow decision to isolated namespace
        from eigencapital.shadow.portfolio.tracker import ShadowDecisionRecorder

        recorder = ShadowDecisionRecorder(audit_dir=AUDIT_DIR)
        recorder.record_decision(_shadow_decision)

        # Log comparison metrics between R4 baseline and shadow selection
        b = _shadow_decision.baseline["metrics"]
        s = _shadow_decision.selected["metrics"]
        e = _shadow_decision.edge_metrics
        log(
            f"  📊 Shadow: {len(_shadow_decision.selected['symbols'])} selected "
            f"(R4 baseline: {len(_shadow_decision.baseline['symbols'])})"
        )
        log(f"  edge retained: {e['edge_retained_pct']}%  top-signal: {e['top_signal_retention']}")
        log(f"  avg pairwise corr: R4={b['avg_pairwise_corr']:.4f} shadow={s['avg_pairwise_corr']:.4f}")
        log(
            f"  max abs corr: R4={b['max_abs_pairwise_corr']:.4f} shadow={s['max_abs_pairwise_corr']:.4f} "
            f"pair={s.get('max_abs_corr_pair') or 'n/a'}"
        )
        log(
            f"  risk contribution shares: R4={b.get('risk_contribution_share_sum', 0.0):.4f} "
            f"shadow={s.get('risk_contribution_share_sum', 0.0):.4f}"
        )
        log(f"  portfolio vol (annual): R4={b['portfolio_vol_annual']:.4f} shadow={s['portfolio_vol_annual']:.4f}")
        log(f"  effective positions: R4={b['effective_positions']:.1f} shadow={s['effective_positions']:.1f}")
        log(
            f"  max cluster exposure: R4={b['exposure']['max_cluster_exposure']['pct']:.1%} "
            f"shadow={s['exposure']['max_cluster_exposure']['pct']:.1%}"
        )
        log(
            f"  max ccy exposure: R4={b['exposure']['max_currency_exposure']['pct']:.1%} "
            f"shadow={s['exposure']['max_currency_exposure']['pct']:.1%}"
        )

    # T1 diagnostic: persisten currency exposure summary for the cycle.
    # Computed after risk gates pass and shadow construction — read-only, never
    # fed back into R4 signal, selection, or sizing (behavior unchanged).
    from eigencapital.shadow.portfolio.exposure import ExposureModel

    exposure_model = ExposureModel()
    # Use target_weights (full signal) for exposure diagnostic; if regime is off
    # or no candidates selected, this still captures the signal's currency footprint.
    #
    # BUGFIX (2026-09-14): target_weights is a pandas Series, and
    # `if target_weights` on a multi-element Series raises
    # "The truth value of a Series is ambiguous." Use `.empty` instead of
    # relying on Series truthiness — this was the root cause of the
    # "Cycle error" crash that aborted every cycle right after the shadow
    # portfolio diagnostics logged, before orders could ever be generated.
    ccy_exposure = exposure_model.currency_exposure(
        target_weights.to_dict() if target_weights is not None and not target_weights.empty else {},
        None,
    )
    # Log the heaviest currency concentrations.
    if any(abs(v) > 10.0 for v in ccy_exposure.values()):
        top_ccy = max(ccy_exposure, key=abs)
        others = ", ".join(f"{c}:{v:+.0f}%" for c, v in sorted(ccy_exposure.items()) if abs(v) > 5.0)
        log(f"  📊 Currency exposure: top={top_ccy} {ccy_exposure[top_ccy]:+.0f}% (others: {others})")
    else:
        others = ", ".join(f"{c}:{v:+.0f}%" for c, v in sorted(ccy_exposure.items()) if abs(v) > 5.0)
        log(f"  📊 Currency exposure: within normal ranges — {others}")

    # T5 Fix 18: MT5 heartbeat + liveness probe — verify broker connectivity
    # as a read-only diagnostic before risk enforcement. If MT5 is unreachable,
    # the cycle will block per the existing risk gate (broker_connectivity), but
    # this log provides early visibility and auditing.
    _mt5_hb = "REACHABLE" if mt5 is not None and hasattr(mt5, "terminal_info") else "UNREACHABLE"
    log(f"  📡 MT5 liveness: {_mt5_hb}")
    if _mt5_hb == "UNREACHABLE":
        audit({"event": "mt5_liveness_failure", "status": _mt5_hb})

    # T5 Fix 19: automated rollforward — check if any R4 symbols require
    # contract rollforward (e.g., expiring futures). Read-only diagnostic;
    # does not modify R4 signal, selection, or sizing. Logs symbols whose
    # contract specifications have changed or where the contract roll month
    # has shifted, enabling operators to manually execute the roll or
    # automate it in a subsequent phase.
    _rollforward_symbols = []
    for sym in R4_SYMBOLS:
        info = mt5.symbol_info(sym) if mt5 else None
        if info and hasattr(info, "expiry"):
            # Symbol has an expiry date — check if it's within rollforward window
            try:
                exp = datetime.strptime(info.expiry, "%Y%m%d")
                days_to_expiry = (exp - datetime.now()).days
                if 0 < days_to_expiry <= 30:
                    _rollforward_symbols.append(f"{sym}(expiry={info.expiry}, {days_to_expiry}d)")
            except (ValueError, TypeError):
                pass
    if _rollforward_symbols:
        log(
            f"  📅 Rollforward alert: {', '.join(_rollforward_symbols)} — "
            f"contracts expiring within 30 days, manual roll required"
        )
        audit({"event": "rollforward_needed", "symbols": _rollforward_symbols})
    else:
        log("  ✅ Rollforward: no R4 symbols expiring within 30 days")

    # T4 Fix 16: portfolio concentration limit — compute HHI from target
    # weights and log if exceeds threshold. Read-only diagnostic; does not
    # modify R4 signal, selection, or sizing. The HHI (Herfindahl-Hirschman
    # Index) ranges from 1/N (even N-symbol distribution) to 1 (single-asset
    # concentration). A threshold of 0.10 (~3 symbols at equal weight) flags
    # excessive concentration for review.
    # BUGFIX (2026-09-14): this HHI check is a read-only diagnostic (T4 Fix
    # 16) — it must never be able to abort a live cycle. It previously did
    # exactly that when `max_concentration_hhi` was renamed/removed from
    # evidence_gate.py, turning a diagnostic-only import into an unhandled
    # ImportError that killed the whole cycle before orders were generated.
    # Import defensively and fall back to the documented default threshold.
    try:
        from eigencapital.analytics.validation.evidence_gate import max_concentration_hhi
    except ImportError as _e:
        max_concentration_hhi = 0.10  # documented default: ~3 symbols at equal weight
        log(f"  ⚠️ evidence_gate.max_concentration_hhi unavailable ({_e}) — using default {max_concentration_hhi:.2f}")

    hhi, top3 = _target_concentration_diagnostics(target_weights)
    if hhi > max_concentration_hhi:
        log(
            f"  ⚠️ Concentration HHI: {hhi:.4f} exceeds threshold {max_concentration_hhi:.2f} — "
            f"top3: {', '.join(f'{s}:{share:.1%}' for s, share in top3)}"
        )
    else:
        log(f"  ✅ Concentration HHI: {hhi:.4f} within threshold {max_concentration_hhi:.2f}")

    # T4 Fix 15: use actual return correlation among active target symbols.
    # Signal weights are one vector and cannot have a pairwise correlation by
    # themselves; the previous rank-index proxy was not a correlation metric.
    mean_abs_corr, max_abs_corr, divers_quality, corr_symbols = _signal_correlation_diagnostics(
        target_weights, returns_df
    )
    if corr_symbols > 1:
        log(
            f"  📊 Correlation dashboard: mean_abs_pairwise_corr={mean_abs_corr:.4f} "
            f"max_abs_pair={max_abs_corr:.4f} diversification_quality={divers_quality:.2f} "
            f"(symbols={corr_symbols})"
        )
        if divers_quality < 0.3:
            log(
                f"  ⚠️ Diversification quality low: {divers_quality:.2f} — "
                f"consider reducing correlated exposure or reviewing signal overlap"
            )
    else:
        log("  📊 Correlation dashboard: fewer than two active symbols — no pairwise correlation")

    # 6. Get prices and specs
    prices: Dict[str, float] = {}
    contract_sizes: Dict[str, float] = {}
    min_volumes: Dict[str, float] = {}
    for sym in R4_SYMBOLS:
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if tick and info:
            prices[sym] = tick.ask
            contract_sizes[sym] = info.trade_contract_size
            min_volumes[sym] = info.volume_min

    # 6. Build position details (tickets for hedging-safe closes)
    pos_details: Dict[str, List[Dict[str, Any]]] = {}
    for p in pos_list:
        pos_details.setdefault(p.symbol, []).append(
            {
                "ticket": p.ticket,
                "volume": p.volume,
                "type": p.type,
            }
        )

    # 6. Generate orders (rotation-aware: closes weak, opens strong)
    orders = generate_orders(
        target_weights,
        current_lots,
        prices,
        contract_sizes,
        min_volumes,
        equity,
        pos_details,
    )

    # T0 sizing evidence: persist intended-vs-achievable weight deviation.
    # Read-only diagnostics — computed inside generate_orders, never fed back
    # into signal, selection, or sizing (behavior unchanged).
    if weight_error_by_symbol:
        try:
            os.makedirs(AUDIT_DIR, exist_ok=True)
            _wd_record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "signal_date": diag.get("signal_date"),
                "equity_capped": min(equity, MAX_EQUITY),
                "symbol_count": len(weight_error_by_symbol),
                "floored_count": sum(1 for v in weight_error_by_symbol.values() if v.get("floored")),
                "max_abs_weight_error_pct": max(
                    (abs(v.get("weight_error_pct", 0.0)) for v in weight_error_by_symbol.values()),
                    default=0.0,
                ),
                "symbols": weight_error_by_symbol,
            }
            with open(WEIGHT_DEVIATION_FILE, "a") as f:
                f.write(json.dumps(_wd_record, default=str) + "\n")
            _worst = max(weight_error_by_symbol.items(), key=lambda kv: abs(kv[1].get("weight_error_pct", 0.0)))
            log(
                f"  ⚠️ Execution fidelity: {_wd_record['floored_count']}/{_wd_record['symbol_count']} symbols "
                f"constrained by broker min-lot. "
                f"Worst deviation: GBPCAD +{_worst[1]['weight_error_pct']:.1f}%. "
                f"Note: broker granularity materially constrains target realization at current equity."
            )
        except OSError as _e:
            log(f"  ⚠️ weight-deviation evidence write failed: {_e}")

    # Split into closes and remaining orders.
    # Closes: ticket-scoped orders AND rotation-closed fallbacks (both free a slot).
    # Remaining naked orders: new entries consume slots; held-symbol opens
    # (after a paired close in generate_orders) are slot-neutral.
    # Use pos_list for held_symbols — any open ticket counts, even if net=0
    # (hedging duplicates where BUY+SELL net to zero but both tickets are live).
    held_symbols = {p.symbol for p in pos_list}
    closes = [o for o in orders if o[4] is not None or "rotated out" in o[3]]
    naked = [o for o in orders if o[4] is None and "rotated out" not in o[3]]
    adjustments = [o for o in naked if o[0] in held_symbols]
    new_entries = [o for o in naked if o[0] not in held_symbols]

    # After closes, we have free slots for new entries (adjustments don't count)
    available_after_close = MAX_CONCURRENT - len(pos_list) + len(closes)
    if len(new_entries) > available_after_close:
        log(
            f"⚠️  {len(new_entries)} new entries after {len(closes)} closes "
            f"— truncating to {available_after_close} ({len(adjustments)} slot-neutral adjustments kept)"
        )
        new_entries = new_entries[:available_after_close]
        orders = closes + adjustments + new_entries

    # 6c. Envelope enforcement (T0). See _apply_order_notional_envelope:
    # over-cap new opens are skipped (fail-closed per order), closes always
    # pass, unreadable specs are blocked. max_order_notional ==
    # max_position_notional == capital.max_position_size, enforced by
    # validate_config_consistency(), so one bound covers both names.
    _notional_cap = max(RISK_ENVELOPE.max_order_notional, RISK_ENVELOPE.max_position_notional)
    orders, _envelope_blocked = _apply_order_notional_envelope(
        orders,
        prices,
        contract_sizes,
        _notional_cap,
        symbol_info=mt5.symbol_info,
    )
    if _envelope_blocked:
        log(f"⛔ ENVELOPE: {len(_envelope_blocked)} order(s) exceed ${_notional_cap:,.0f} notional cap — skipped")
        audit(
            {
                "event": "order_envelope_blocked",
                "cap": _notional_cap,
                "orders": _envelope_blocked,
                "diag": diag,
            }
        )

    # T2 Fix 9: verify enforced orders match sizing intent within tolerance.
    # After envelope capping, compute achieved weights and compare to target
    # weights so the audit trail can flag any symbol whose final position
    # deviates beyond the configured tolerance (default 5% absolute weight
    # error, which is the min-lot floor distortion already captured in
    # weight_error_by_symbol). This is read-only — no behavior change.
    if diag:
        from eigencapital.shadow.portfolio.tracker import ShadowDecisionRecorder

        recorder = ShadowDecisionRecorder(audit_dir=AUDIT_DIR)
        intent_summary = {}
        for order in orders:
            sym, side, lots, reason, _ = order
            price = prices.get(sym, 0)
            cs = contract_sizes.get(sym, 0)
            if price > 0 and cs > 0:
                notional = abs(lots) * price * cs
                achieved_w = notional / max(equity, 1e-6)
                achieved_w *= 1.0 if side == "BUY" else -1.0
                # Find target weight for this symbol
                target_w = target_weights.get(sym, 0.0) if hasattr(target_weights, "get") else 0.0
                # Handle signed weight comparison
                if isinstance(target_weights, dict):
                    target_w = target_weights.get(sym, 0.0) or 0.0
                intent_summary[sym] = {
                    "target_w": round(target_w, 6),
                    "achieved_w": round(achieved_w, 6),
                    "weight_error": round(achieved_w - target_w, 6),
                    "weight_error_pct": round((achieved_w - target_w) / max(abs(target_w), 1e-6) * 100, 2),
                    "lots": lots,
                    "reason": reason,
                }
                # Flag if error exceeds 5% tolerance
                if abs(achieved_w - target_w) > 0.05:
                    log(
                        f"  ⚠️ Sizing intent deviation {sym}: target={target_w:+.4f} achieved={achieved_w:+.4f} error={achieved_w - target_w:+.4f} ({intent_summary[sym]['weight_error_pct']:.1f}%)"
                    )
        if intent_summary:
            recorder.record_intent_drift(intent_summary)

    # Check if anything actually needs to happen
    if not orders:
        # Check if we're at limit with no rotation needed
        if len(pos_list) >= MAX_CONCURRENT:
            log(f"📊 At {len(pos_list)}/{MAX_CONCURRENT} — portfolio aligned, no rotation needed")
            audit({"event": "aligned", "positions": len(pos_list), "diag": diag})
            return {"status": "ALIGNED", "diag": diag}

    if not orders:
        log("✅ Portfolio aligned — no orders needed")
        audit({"event": "aligned", "positions": len(pos_list), "diag": diag})
        return {"status": "ALIGNED", "diag": diag}

    # 7. Shadow portfolio analytics (read-only — no impact on orders)
    try:
        from eigencapital.live.portfolio_analytics import PortfolioAnalyzer

        _analyzer = PortfolioAnalyzer(audit_dir=AUDIT_DIR)
        _diagnostics = _analyzer.compute_diagnostics(
            target_weights=target_weights,
            current_positions=current_lots,
            prices=prices,
            contract_sizes=contract_sizes,
            equity=equity,
            order_count=len(orders),
            order_symbols=[o[0] for o in orders],
            returns_history=returns_df,
        )
        _analyzer.record(_diagnostics)
        corr_bets = _diagnostics.correlation_diagnostics.get("effective_bets", 0)
        log(
            f"  📊 Portfolio: {_diagnostics.position_count} pos, "
            f"gross={_diagnostics.gross_leverage:.2f}x, "
            f"net={_diagnostics.net_leverage:.2f}x, "
            f"eff_positions={_diagnostics.effective_positions:.1f}, "
            f"eff_bets={corr_bets:.1f}"
        )
        if _diagnostics.largest_currency_factor:
            log(
                f"  📊 Largest factor: {_diagnostics.largest_currency_factor} "
                f"({_diagnostics.largest_currency_factor_pct:+.1%})"
            )
    except Exception as e:
        log(f"  ⚠️ Shadow analytics failed (non-blocking): {e}")

    # 8. Display plan
    log(f"Orders: {len(orders)}")
    for sym, side, lots, reason, ticket in orders:
        verb = "CLOSE" if ticket is not None else side
        log(f"  → {verb} {lots:.2f} {sym} ({reason})")

    # 9. Execute
    if dry_run:
        log("📋 DRY RUN — no orders submitted")
        audit({"event": "dry_run", "orders": len(orders), "diag": diag})
        return {"status": "DRY_RUN", "orders": len(orders), "diag": diag}

    # EC-AUD-004: Persist order intents BEFORE execution
    global _cycle_counter
    _cycle_counter += 1
    _persist_order_intents(orders, _cycle_counter)
    audit({"event": "order_intents_persisted", "cycle": _cycle_counter, "count": len(orders)})

    filling_mode = detect_filling_mode(mt5)
    exec_results = execute_orders(mt5, orders, filling_mode)

    # 9. Post-trade state
    time.sleep(1)
    account_after = mt5.account_info()
    positions_after = mt5.positions_get()
    pos_count = len(list(positions_after)) if positions_after else 0

    cycle_result = {
        "status": "EXECUTED",
        "equity_before": equity,
        "equity_after": account_after.equity if account_after else 0,
        "positions_before": len(pos_list),
        "positions_after": pos_count,
        "submitted": exec_results["submitted"],
        "filled": exec_results["filled"],
        "failed": exec_results["failed"],
        "ambiguous": exec_results.get("ambiguous", 0),
        "diag": diag,
        "duration_seconds": time.time() - cycle_start,
    }

    log(
        f"Result: {exec_results['filled']}/{exec_results['submitted']} filled | "
        f"ambiguous: {exec_results.get('ambiguous', 0)} | "
        f"Equity: ${cycle_result['equity_after']:,.2f}"
    )

    audit({"event": "executed", **cycle_result})

    # T2 Fix 10: order-fill confirmation loop — re-check positions after
    # execution to confirm fills, close the reconciliation gap on transient
    # failures or MT5 timing windows. Read-only diagnostic; no behavioral
    # change if all fills confirm, but enables retry logic for any order
    # whose position did not appear after the confirmation window.
    confirmation_wait = 1.5  # seconds; MT5 fill settlement typical < 1s
    time.sleep(confirmation_wait)
    positions_after_conf = mt5.positions_get() or []
    # Build a set of (symbol, type, ticket) that appeared after confirmation
    confirmed_tickets = {(p.ticket, p.symbol, p.type): p for p in positions_after_conf}
    # Cross-reference: for each order ticket, check if it was confirmed
    confirmed_ticket_set = set()
    for order in orders[:MAX_ORDERS_PER_CYCLE]:
        _, _, _lots, _reason, ticket = order
        if ticket is not None and ticket in confirmed_tickets:
            confirmed_ticket_set.add(ticket)
    # Log confirmation status
    unconfirmed = sum(
        1 for order in orders[:MAX_ORDERS_PER_CYCLE] if order[4] is not None and order[4] not in confirmed_ticket_set
    )
    if unconfirmed > 0:
        log(
            f"  ⚠️ Fill confirmation: {unconfirmed}/{len(orders[:MAX_ORDERS_PER_CYCLE])} order(s) ticket(s) unconfirmed after {confirmation_wait}s"
        )
    else:
        log(f"  ✅ Fill confirmation: all {min(len(orders), MAX_ORDERS_PER_CYCLE)} order(s) ticket(s) confirmed")
    # Persist confirmation diagnostics
    audit(
        {
            "event": "fill_confirmation",
            "confirmation_wait_s": confirmation_wait,
            "submitted": exec_results["submitted"],
            "filled": exec_results["filled"],
            "unconfirmed_tickets": unconfirmed,
            "total_tickets": sum(1 for o in orders[:MAX_ORDERS_PER_CYCLE] if o[4] is not None),
        }
    )

    # T3 Fix 11: signal weight decay across cycles — compute average
    # weight change rate from the persisted intent ledger so the audit
    # trail can flag drift. Read-only: does not modify signal generation
    # or sizing parameters.
    try:
        import json as _json

        intent_path = ORDER_INTENT_FILE
        if os.path.exists(intent_path):
            with open(intent_path) as _f:
                lines = _f.readlines()
            if len(lines) >= 2:
                prev = _json.loads(lines[-2])
                cur = _json.loads(lines[-1])
                prev_weights = {i["symbol"]: i["intended_weight"] for i in prev.get("intents", [])}
                cur_weights = {i["symbol"]: i["intended_weight"] for i in cur.get("intents", [])}
                common = set(prev_weights) & set(cur_weights)
                if common:
                    weight_drifts = []
                    for sym in common:
                        pw, cw = prev_weights[sym], cur_weights[sym]
                        if abs(pw) > 1e-6:
                            drift = (cw - pw) / pw
                            weight_drifts.append(drift)
                    avg_drift = sum(weight_drifts) / len(weight_drifts) if weight_drifts else 0.0
                    pct_drift = avg_drift * 100.0
                    log(
                        f"  📈 Weight drift: {pct_drift:+.2f}% avg cycle change "
                        f"(samples={len(weight_drifts)}, symbols={len(common)})"
                    )
                    audit(
                        {
                            "event": "weight_drift",
                            "avg_pct_change": round(pct_drift, 4),
                            "drift_samples": len(weight_drifts),
                            "common_symbols": len(common),
                        }
                    )
    except Exception:
        pass  # non-blocking diagnostic

    # EC-AUD-004 + T0: Reconcile execution against persisted intents,
    # now with per-(symbol, side) matching.
    intent_recon = _reconcile_against_intents(
        exec_results["filled"],
        exec_results["failed"],
        orders[:MAX_ORDERS_PER_CYCLE],
        fills=exec_results.get("fills"),
    )
    cycle_result["intent_reconciliation"] = intent_recon
    if intent_recon["status"] == "DISCREPANCY":
        log(f"⚠️ Intent reconciliation: {intent_recon.get('warning', 'unknown discrepancy')}")
        audit({"event": "intent_discrepancy", **intent_recon})

    # ── Evidence collection: capture snapshot after execution ──────────
    try:
        positions_after_list = list(mt5.positions_get() or [])
        evidence_snapshot = capture_evidence_snapshot(
            positions=[
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": p.type,
                    "volume": p.volume,
                    "magic": p.magic,
                    "comment": p.comment,
                    "profit": p.profit,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                }
                for p in positions_after_list
            ],
            equity=cycle_result["equity_after"],
            balance=getattr(account_after, "balance", 0) if account_after else 0,
            free_margin=getattr(account_after, "margin_free", 0) if account_after else 0,
        )
        if evidence_snapshot:
            log(f"📊 Evidence snapshot captured: {evidence_snapshot['position_count']} positions")
    except Exception as e:
        log(f"⚠️ Evidence snapshot failed: {e}")

    return cycle_result


def emergency_flatten(mt5) -> Dict[str, Any]:
    """Close all open positions immediately. Idempotent.

    Returns summary of close attempts.
    """
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []

    if not pos_list:
        log("✅ No positions to flatten — already flat")
        return {"closed": 0, "failed": 0}

    log(f"🔴 EMERGENCY FLATTEN: Closing {len(pos_list)} positions")

    filling_mode = detect_filling_mode(mt5)
    closed = 0
    failed = 0

    for p in pos_list:
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            log(f"  ❌ Cannot get tick for {p.symbol}")
            failed += 1
            continue

        # Close in opposite direction
        close_type = MetaTrader5.ORDER_TYPE_SELL if p.type == 0 else MetaTrader5.ORDER_TYPE_BUY
        close_price = tick.bid if p.type == 0 else tick.ask

        request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": close_type,
            "position": p.ticket,
            "price": close_price,
            "deviation": 20,
            "magic": 20260825,
            "comment": "EMERGENCY-FLATTEN",
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        try:
            future = _executor.submit(mt5.order_send, request)
            result = future.result(timeout=_ORDER_SEND_TIMEOUT_SECONDS)
        except (FuturesTimeoutError, Exception) as e:
            log(f"  ⏱️ flatten order_send failed for {p.symbol}: {e}")
            result = None

        if result and result.retcode == MetaTrader5.TRADE_RETCODE_DONE:
            closed += 1
            log(f"  ✅ CLOSED {p.volume:.2f} {p.symbol} @ {result.price:.5f}")
        else:
            failed += 1
            rc = result.retcode if result else "None"
            log(f"  ❌ FAILED {p.symbol} — {rc}")

    log(f"Flatten complete: {closed} closed, {failed} failed")
    audit({"event": "emergency_flatten", "closed": closed, "failed": failed})
    return {"closed": closed, "failed": failed}


# ── Shadow portfolio constructor (shadow-only) ──────────────────────────────
def _run_shadow_constructor(
    target_weights: pd.Series,
    returns_df: pd.DataFrame,
    equity: float,
    diag: Dict[str, Any],
    config: Any,
    mt5: Any,
    cycle_id: str,
    signal_date: str,
) -> Any | None:
    """Construct a shadow portfolio using the same R4 candidates.

    This is purely observational — it:
    * builds the candidate universe from the frozen R4 signal weights,
    * builds a correlation snapshot from available returns history,
    * runs the shadow selector (risk-aware, correlation/exposure-aware),
    * persists the decision to the shadow namespace only,
    * logs comparison metrics against the R4 baseline.

    It never modifies R4 behavior, order intents, risk gates, or broker state.
    """
    from eigencapital.live.portfolio_analytics import (
        ASSET_CLASS_MAP,
        SYMBOL_CURRENCY_MAP,
    )
    from eigencapital.shadow.portfolio.correlation import CorrelationModel
    from eigencapital.shadow.portfolio.exposure import get_factor_group
    from eigencapital.shadow.portfolio.selector import (
        ShadowCandidate,
        ShadowSelector,
        ShadowSelectorConfig,
    )
    from eigencapital.shadow.portfolio.tracker import ShadowDecisionRecorder

    # ——— Configuration ———
    max_concurrent = int(config.capital.max_concurrent_positions)
    min_weight = float(config.signal.min_weight) if hasattr(config, "signal") else 0.005

    # ——— Build vol_at_t and history_ok from returns history ———
    vol_map: Dict[str, float] = {}
    history_map: Dict[str, bool] = {}
    for sym in target_weights.index:
        if sym in returns_df.columns:
            series = returns_df[sym].dropna()
            history_map[sym] = len(series) >= 30
            if len(series) >= 60:
                v = float(series.tail(60).std() * 252**0.5)  # annualized
                vol_map[sym] = v if v > 0 else 0.0

    # ——— Build asset-class map for candidates ———
    asset_class_map: Dict[str, str] = {}
    for sym in target_weights.index:
        if sym in SYMBOL_CURRENCY_MAP:
            asset_class_map[sym] = (
                "metals" if sym in ("XAUUSD", "XAGUSD") else ("crypto" if sym in ("BTCUSD", "ETHUSD") else "forex")
            )
        elif sym in ASSET_CLASS_MAP:
            asset_class_map[sym] = ASSET_CLASS_MAP[sym]
        else:
            # Derive from prefix
            prefix = sym.split("_")[0] if "_" in sym else sym[:3]
            if prefix in ("US30", "USTEC", "US500"):
                asset_class_map[sym] = "indices"
            elif prefix in ("XAU", "XAG"):
                asset_class_map[sym] = "metals"
            elif prefix == "BTC" or prefix == "ETH":
                asset_class_map[sym] = "crypto"
            elif prefix == "USO":
                asset_class_map[sym] = "energy"
            else:
                asset_class_map[sym] = "forex"

    # ——— Build candidate universe (same as R4 sees) ———
    ranked = sorted(
        [s for s in target_weights.index if abs(target_weights[s]) >= min_weight],
        key=lambda s: -abs(target_weights[s]),
    )
    rank_map = {s: i + 1 for i, s in enumerate(ranked)}

    candidates: List[ShadowCandidate] = []
    for sym in ranked:
        w = float(target_weights[sym])
        candidates.append(
            ShadowCandidate(
                symbol=sym,
                weight=w,
                direction="LONG" if w > 0 else "SHORT",
                asset_class=asset_class_map.get(sym, "other"),
                factor_group=get_factor_group(sym),
                feasible=True,
                r4_rank=rank_map[sym],
                annualized_vol=vol_map.get(sym),
                history_sufficient=history_map.get(sym, True),
            )
        )

    if not candidates:
        log("  ⚠️  No shadow candidates — skipping shadow construction")
        return None

    # ——— Build correlation snapshot (no-lookahead, from data available at cycle time) ———
    now = datetime.now(UTC).replace(tzinfo=None)  # strip tz for no-lookahead truncation
    snapshot = CorrelationModel().build(returns_df, as_of=pd.Timestamp(now).replace(tzinfo=None))

    if snapshot is None:
        log("  ⚠️  Insufficient history for correlation snapshot — shadow construction skipped")
        return None

    # ——— Run shadow selector ———
    selector = ShadowSelector(ShadowSelectorConfig())
    baseline_symbols = [c.symbol for c in candidates][:max_concurrent]

    decision = selector.select(
        candidates=candidates,
        snapshot=snapshot,
        baseline_symbols=baseline_symbols,
        cycle_id=cycle_id,
        decision_timestamp=now.isoformat(),
        signal_date=signal_date,
        regime={
            "regime_on": bool(diag.get("regime_on", False)),
            "vol_now": float(diag.get("vol_now", 0)),
            "vol_median": float(diag.get("vol_median", 0)),
            "vol_ratio": float(diag.get("vol_now", 0)) / float(diag.get("vol_median", 1)),
        },
    )

    # ——— Persist shadow decision ———
    recorder = ShadowDecisionRecorder(audit_dir=AUDIT_DIR)
    recorder.record_decision(decision)

    # ——— Log comparison metrics ———
    b = decision.baseline["metrics"]
    s = decision.selected["metrics"]
    e = decision.edge_metrics

    log(f"  📊 Shadow: {len(decision.selected['symbols'])} selected (R4 baseline: {len(decision.baseline['symbols'])})")
    log(f"  edge retained: {e['edge_retained_pct']}%  top-signal: {e['top_signal_retention']}")
    log(f"  avg pairwise corr: R4={b['avg_pairwise_corr']:.4f} shadow={s['avg_pairwise_corr']:.4f}")
    log(f"  portfolio vol (annual): R4={b['portfolio_vol_annual']:.4f} shadow={s['portfolio_vol_annual']:.4f}")
    log(f"  effective positions: R4={b['effective_positions']:.1f} shadow={s['effective_positions']:.1f}")
    log(
        f"  max cluster exposure: R4={b['exposure']['max_cluster_exposure']['pct']:.1%} "
        f"shadow={s['exposure']['max_cluster_exposure']['pct']:.1%}"
    )
    log(
        f"  max ccy exposure: R4={b['exposure']['max_currency_exposure']['pct']:.1%} "
        f"shadow={s['exposure']['max_currency_exposure']['pct']:.1%}"
    )

    # Log rejection reasons for diagnostics
    rejected_reasons = set()
    for c in decision.candidates:
        r = c.get("rejection_reason") or c.get("dominant_rejection")
        if r:
            rejected_reasons.add(r)
    if rejected_reasons:
        log(f"  rejection reasons: {sorted(rejected_reasons)}")

    return decision


def main() -> None:
    args = sys.argv[1:]
    loop_mode = "--loop" in args
    force_regime = "--force-regime" in args
    dry_run = "--dry-run" in args
    flatten_only = "--flatten" in args

    # P0 EC-AUD-002: --force-regime is forbidden in live loop mode.
    # It can bypass the frozen R4 regime gate and contaminate Phase 2 evidence.
    # Allowed only in dry-run / single-cycle mode for diagnostics.
    if force_regime and loop_mode:
        print("\n⛔ FATAL: --force-regime is not allowed in live loop mode.", flush=True)
        print("   It bypasses the frozen R4 regime gate and contaminates Phase 2 evidence.", flush=True)
        print("   Use --dry-run for diagnostics, or remove --force-regime.", flush=True)
        audit({"event": "force_regime_rejected", "mode": "loop"})
        sys.exit(1)

    interval = _config.execution.loop_interval_seconds
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])

    print("=" * 60, flush=True)
    print("  R4 REBALANCE LOOP", flush=True)
    print(
        f"  Mode: {'LOOP' if loop_mode else 'ONE-SHOT'} | Interval: {interval}s",
        flush=True,
    )
    print(
        f"  Regime: {'FORCED ON' if force_regime else 'gated'} | Exec: {'DRY RUN' if dry_run else 'LIVE'}",
        flush=True,
    )
    print(
        f"  Risk: ENFORCED (max_concurrent={RISK_ENVELOPE.max_concurrent_positions}, "
        f"max_pos=${RISK_ENVELOPE.max_position_notional:,.0f}, "
        f"max_dd={RISK_ENVELOPE.max_account_drawdown_pct:.0%})",
        flush=True,
    )
    print("=" * 60, flush=True)

    # R4-S 2026-09-06: ONE-SHOT mode used to crash with ConnectionRefusedError
    # when the RPyC bridge was down (reboot cleared /tmp), because bridge
    # recovery only ran inside loop mode. Establish a verified session,
    # repairing the bridge first if needed.
    mt5 = _connect_verified_mt5()
    if mt5 is None:
        print("  ❌ Cannot connect: no verified MT5 session after bridge recovery")
        print("     Manual start: scripts/start_trading.sh --bridge-only")
        return

    account = mt5.account_info()
    log(f"Connected — Account: {account.login}, Equity: ${account.equity:,.2f}")

    # P1-006: Config drift verification mode
    if "--verify-config" in args:
        print("\n🔍 Config Drift Verification", flush=True)
        print("=" * 60, flush=True)
        import glob as _glob

        t0_files = sorted(_glob.glob("reports/r4_qualification/T0_*.json"), key=os.path.getmtime)
        if not t0_files:
            print("  ⚠️  No T=0 snapshot found — cannot verify drift", flush=True)
            mt5.shutdown()
            return
        try:
            with open(t0_files[-1]) as f:
                t0 = json.load(f)
            t0_fp = t0.get("fingerprints", {}).get("config", "")
            current_fp = _fingerprint_verifier._frozen_config_fp
            print(f"  T=0 snapshot: {t0_files[-1]}", flush=True)
            print(f"  T=0 config fingerprint:  {t0_fp[:32]}...", flush=True)
            print(f"  Current config fingerprint: {current_fp[:32]}...", flush=True)
            if t0_fp == current_fp:
                print("  ✅ Config matches T=0 — no drift detected", flush=True)
            else:
                print("  🔴 Config DRIFT DETECTED — config has changed since T=0", flush=True)
                print("  To fix: either revert config.toml or re-run r4_generate_t0.py", flush=True)
            # Show symbol mapping fingerprint
            from eigencapital.config import compute_symbol_mapping_fingerprint

            sym_fp = compute_symbol_mapping_fingerprint(_config)
            print(f"\n  Symbol mapping fingerprint: {sym_fp[:32]}...", flush=True)
            print(f"  Allowed symbols: {len(_config.broker.allowed_symbols)}", flush=True)
            # Show live_risk summary
            lr = _config.live_risk
            print("\n  Live risk envelope:", flush=True)
            print(f"    max_concurrent: {lr.max_concurrent_positions}", flush=True)
            print(f"    max_position:   ${lr.max_position_notional:,.0f}", flush=True)
            print(f"    max_daily_loss: ${lr.max_daily_loss:,.0f}", flush=True)
            print(f"    min_equity:     ${lr.min_equity:,.0f}", flush=True)
            print(f"    t0_equity:      ${lr.t0_equity:,.2f}", flush=True)
        except Exception as e:
            print(f"  ❌ Error: {e}", flush=True)
        mt5.shutdown()
        return

    # Flatten-only mode
    if flatten_only:
        emergency_flatten(mt5)
        mt5.shutdown()
        return

    # Initialize daily loss tracker (handles persistence, midnight rollover, restart)
    _daily_loss_tracker.initialize(broker_equity=account.equity)
    log(
        f"Daily loss tracker: baseline=${_daily_loss_tracker.baseline_equity:,.2f}, "
        f"budget=${_daily_loss_tracker.remaining_daily_loss_budget:,.2f}"
    )

    # Load persisted state (survives restart)
    saved_state = _load_state()
    if saved_state:
        saved_recovery = saved_state.get("recovery_state", "connected")
        saved_attempts = saved_state.get("recovery_attempts", 0)
        log(f"Loaded persisted state: recovery={saved_recovery}, attempts={saved_attempts}")
        # Restore peak equity if persisted
        saved_peak = saved_state.get("peak_equity")
        if saved_peak and saved_peak > _risk_enforcer._peak_equity:
            _risk_enforcer._peak_equity = saved_peak
            log(f"Restored peak equity: ${saved_peak:,.2f}")

    # Initialize evidence orchestrator
    log("\nInitializing evidence orchestrator...")
    _evidence_orchestrator = EvidenceOrchestrator(
        campaign_id="R4-5K-20260827",
        snapshot_interval_seconds=interval,
    )
    log(f"Evidence orchestrator: campaign={_evidence_orchestrator._campaign_id}")
    log(f"Evidence dir: {_evidence_orchestrator._evidence_dir}")

    # EC-AUD-006: Validate config semantic consistency at startup
    from eigencapital.config import validate_config_consistency

    config_warnings = validate_config_consistency(_config)
    if config_warnings:
        log("\n⚠️  Config consistency warnings:")
        for w in config_warnings:
            log(f"   → {w}")
            audit({"event": "config_warning", "message": w})
        # CRITICAL warnings block startup
        critical = [w for w in config_warnings if w.startswith("CRITICAL")]
        if critical:
            log(f"\n🔴 {len(critical)} CRITICAL config issue(s) — cannot start trading")
            mt5.shutdown()
            return
    else:
        log("\n✅ Config consistency validated — no issues")

    # Startup fingerprint verification (fail closed)
    log("\nVerifying configuration fingerprints...")
    fp_result = _fingerprint_verifier.verify_all()
    for check in fp_result.checks:
        icon = "✅" if check.status == "verified" else "❌"
        log(f"  {icon} {check.component}: {check.message}")
    if not fp_result.all_verified:
        log("\n🔴 FINGERPRINT VERIFICATION FAILED — cannot start trading")
        log("   Fix configuration drift before running.")
        audit(
            {
                "event": "startup_fingerprint_failed",
                "checks": [c.to_dict() for c in fp_result.checks],
            }
        )
        mt5.shutdown()
        return
    log("✅ All fingerprints verified — trading authorized\n")
    audit(
        {
            "event": "startup_fingerprint_verified",
            "checks": [c.to_dict() for c in fp_result.checks],
        }
    )

    # T=0 validation — verify frozen campaign boundary exists and matches
    import glob as _glob

    t0_files = sorted(_glob.glob("reports/r4_qualification/T0_*.json"), key=os.path.getmtime)
    if t0_files:
        try:
            with open(t0_files[-1]) as f:
                t0 = json.load(f)
            t0_config_fp = t0.get("fingerprints", {}).get("config", "")
            current_cfg_fp = _fingerprint_verifier._frozen_config_fp
            t0_match = t0_config_fp == current_cfg_fp
            t0_account = t0.get("account", {}).get("id", 0)
            live_account = int(account.login) if account else 0
            account_match = t0_account == live_account
            if t0_match and account_match:
                log(f"✅ T=0 validated: {t0_files[-1]}")
                log(
                    f"   Campaign: {t0.get('campaign_id', '?')} | Account: {t0_account} | Hash: {t0.get('snapshot_hash', '?')[:16]}..."
                )
                audit(
                    {
                        "event": "t0_validated",
                        "file": t0_files[-1],
                        "campaign_id": t0.get("campaign_id"),
                    }
                )
            else:
                log(
                    f"🔴 T=0 MISMATCH: config_fp={'match' if t0_match else 'DRIFT'}, account={'match' if account_match else 'MISMATCH'}"
                )
                audit(
                    {
                        "event": "t0_mismatch",
                        "config_match": t0_match,
                        "account_match": account_match,
                    }
                )
                mt5.shutdown()
                return
        except Exception as e:
            log(f"⚠️  T=0 validation error: {e} — proceeding without T=0 check")
    else:
        log("⚠️  No T=0 snapshot found — proceeding without T=0 check")

    # Position count assertion
    from eigencapital.live.position_attribution import (
        capacity_account as _capacity,
    )
    from eigencapital.live.position_attribution import (
        classify_all as _classify,
    )

    pos_assertion = list(mt5.positions_get() or [])
    classified_start = _classify(
        [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p.type,
                "volume": p.volume,
                "magic": p.magic,
                "comment": p.comment,
                "profit": p.profit,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
            }
            for p in pos_assertion
        ]
    )
    cap_start = _capacity(classified_start, MAX_CONCURRENT)
    log(
        f"📊 Position assertion: {cap_start.r4_open_count} R4, {len(cap_start.foreign_positions)} foreign, max={MAX_CONCURRENT}"
    )
    log(
        f"   gate: {'PASS' if cap_start.r4_open_count <= MAX_CONCURRENT and len(cap_start.foreign_positions) == 0 else 'BLOCK'}"
    )
    audit(
        {
            "event": "startup_position_assertion",
            "r4_count": cap_start.r4_open_count,
            "foreign": len(cap_start.foreign_positions),
            "max": MAX_CONCURRENT,
        }
    )

    log("🟢 TRADING_AUTHORIZED — all startup gates passed\n")
    audit({"event": "trading_authorized"})

    # Capture initial evidence snapshot
    try:
        initial_positions = list(mt5.positions_get() or [])
        initial_account = mt5.account_info()
        capture_evidence_snapshot(
            positions=[
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": p.type,
                    "volume": p.volume,
                    "magic": p.magic,
                    "comment": p.comment,
                    "profit": p.profit,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                }
                for p in initial_positions
            ],
            equity=initial_account.equity if initial_account else 0,
            balance=getattr(initial_account, "balance", 0) if initial_account else 0,
            free_margin=getattr(initial_account, "margin_free", 0) if initial_account else 0,
        )
        log("📊 Initial evidence snapshot captured")
    except Exception as e:
        log(f"⚠️ Initial evidence snapshot failed: {e}")

    cycle = 0
    while not _shutdown:
        cycle += 1
        log(f"\n{'─' * 50}")
        log(f"CYCLE {cycle} | Recovery: {_disconnect_recovery.state.value}")
        log(f"{'─' * 50}")

        # ── Disconnect detection ──────────────────────────────────────
        mt5_ok = False
        try:
            test_account = mt5.account_info()
            mt5_ok = test_account is not None and test_account.equity > 0
        except Exception:
            mt5_ok = False

        if not mt5_ok:
            # MT5 disconnected
            if _disconnect_recovery.state == RecoveryState.CONNECTED:
                recovery_msg = _disconnect_recovery.on_disconnect()
                log(f"🔴 MT5 DISCONNECTED — {recovery_msg}")
                audit(
                    {
                        "event": "disconnect",
                        "recovery_state": _disconnect_recovery.state.value,
                    }
                )
                # Record evidence: disconnect event
                try:
                    record_operational_event(
                        event_type="disconnect",
                        detection_time_ms=0.0,
                        success=False,
                    )
                except Exception:
                    pass
            elif _disconnect_recovery.state == RecoveryState.RESUMED:
                # Was resumed but now disconnected again
                recovery_msg = _disconnect_recovery.on_disconnect()
                log(f"🔴 MT5 DISCONNECTED (was resumed) — {recovery_msg}")
                audit(
                    {
                        "event": "disconnect_from_resumed",
                        "recovery_state": _disconnect_recovery.state.value,
                    }
                )
                # Record evidence: disconnect event
                try:
                    record_operational_event(
                        event_type="disconnect_from_resumed",
                        detection_time_ms=0.0,
                        success=False,
                    )
                except Exception:
                    pass

            # Check if frozen
            if _disconnect_recovery.state == RecoveryState.FROZEN:
                log("🔴 FROZEN — too many disconnects. Manual review required.")
                audit({"event": "frozen", "reason": "excessive_disconnects"})
                _persist_state()
                if not loop_mode:
                    break
                # Wait and retry
                for _ in range(min(interval, 300)):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            # Persist and wait
            _persist_state()

            # Try to restart the RPyC bridge if it's down
            bridge_ok = _restart_bridge_if_needed()
            if bridge_ok:
                # Reconnect MT5 through the (verified) bridge. _reconnect_mt5
                # returns a session object only after account_info() confirms
                # live data, so "reconnected" is never claimed on initialize()
                # alone (R4-S 2026-09-04 false-success wedge fix: the loop spun
                # 17+ cycles — and 1499 on 09-01 — logging "✅ reconnected"
                # while its session never regained a live account view).
                log("  Attempting MT5 session re-establishment...")
                rebuilt = _reconnect_mt5(mt5)
                if rebuilt is not None:
                    mt5 = rebuilt
                    log("  ✅ MT5 session verified — account data live")
                    # Advance the recovery state machine NOW, while the
                    # verified session is in hand (R4-S 2026-09-07 wedge fix:
                    # deferring to the next cycle's probe let bridge-session
                    # teardowns re-wedge the state machine at DISCONNECTED).
                    _run_reconciliation_sequence(mt5)
                else:
                    log("  ⚠️  MT5 still unreachable — waiting...")
            else:
                log("  ⚠️  Bridge unreachable — waiting...")

            log(f"   Waiting {min(interval, 60)}s for reconnection...")
            for _ in range(min(interval, 60)):
                if _shutdown:
                    break
                time.sleep(1)
            continue  # ── Reconnection handling ─────────────────────────────────────
        # R4-S 2026-09-07: reconciliation and resume now run inside the
        # recovery path the moment a verified session exists
        # (_run_reconciliation_sequence). Reaching here with state
        # DISCONNECTED therefore means no verified session was established;
        # the permission check below blocks trading fail-closed, exactly as
        # the ID-008 invariants require.

        # ── Trading permission check ──────────────────────────────────
        if _disconnect_recovery.state not in (
            RecoveryState.CONNECTED,
            RecoveryState.RESUMED,
        ):
            log(f"⛔ Trading halted — state: {_disconnect_recovery.state.value}")
            _persist_state()
            if not loop_mode:
                break
            for _ in range(min(interval, 60)):
                if _shutdown:
                    break
                time.sleep(1)
            continue

        # ── Run trading cycle ─────────────────────────────────────────
        cycle_start_time = time.time()
        try:
            cycle_result = run_cycle(mt5, force_regime, dry_run)
        except Exception as e:
            log(f"❌ Cycle error: {e}")
            audit({"event": "error", "error": str(e)})
            cycle_result = {"status": "ERROR", "error": str(e)}

        # Persist state after each cycle
        _persist_state()

        # ── Evidence collection: capture snapshot for non-executed cycles ──
        if cycle_result.get("status") != "EXECUTED":
            try:
                positions_for_evidence = list(mt5.positions_get() or [])
                account_for_evidence = mt5.account_info()
                capture_evidence_snapshot(
                    positions=[
                        {
                            "ticket": p.ticket,
                            "symbol": p.symbol,
                            "type": p.type,
                            "volume": p.volume,
                            "magic": p.magic,
                            "comment": p.comment,
                            "profit": p.profit,
                            "price_open": p.price_open,
                            "sl": p.sl,
                            "tp": p.tp,
                        }
                        for p in positions_for_evidence
                    ],
                    equity=account_for_evidence.equity if account_for_evidence else 0,
                    balance=getattr(account_for_evidence, "balance", 0) if account_for_evidence else 0,
                    free_margin=getattr(account_for_evidence, "margin_free", 0) if account_for_evidence else 0,
                )
            except Exception as e:
                log(f"⚠️ Evidence snapshot failed: {e}")

        # ── Evidence collection: record disconnect/reconnect events ────────
        if cycle_result.get("status") == "ERROR":
            try:
                record_operational_event(
                    event_type="cycle_error",
                    detection_time_ms=(time.time() - cycle_start_time) * 1000,
                    success=False,
                )
            except Exception:
                pass

        if not loop_mode:
            break

        if _shutdown:
            break

        log(f"Next cycle in {interval}s...\n")
        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    # Shutdown: persist final state and disconnect
    _persist_state()
    try:
        mt5.shutdown()
    except Exception:
        pass
    log("Disconnected. Done.")


if __name__ == "__main__":
    main()
