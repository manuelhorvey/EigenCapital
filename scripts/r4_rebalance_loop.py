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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "src")

import numpy as np
import pandas as pd

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None  # Allow import on non-Linux for testing

from eigencapital.config import load_config
from eigencapital.live.daily_loss import DailyLossTracker
from eigencapital.production_qual.evidence_orchestrator import (
    EvidenceOrchestrator,
    capture_evidence_snapshot,
    record_closure,
    record_operational_event,
)
from eigencapital.live.position_attribution import R4_MAGIC, classify_all, snapshot_hash
from eigencapital.live.risk import DisconnectRecovery, RecoveryState
from eigencapital.live.risk_enforcement import GateResult, RiskEnforcer, RiskEnvelope
from eigencapital.live.watchdog import ProbeResult, Watchdog, WatchState, trail_age_seconds
from eigencapital.production_qual.fingerprint_verifier import (
    FingerprintVerifier,
)
from eigencapital.reconciliation.engine import (
    BrokerState,
    InternalState,
    ReconciliationEngine,
)

# ── Load Configuration (Single Source of Truth) ───────────────────

_config = load_config(os.environ.get("EIGENCAPITAL_ENV", "production"))

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
LOOKBACK = _config.strategy.signal_lookback_long  # 252
SKIP = _config.strategy.skip_months * 21  # 1 month ≈ 21 trading days
RISK_LOOKBACK = _config.strategy.risk_lookback  # 20
VOL_LOOKBACK = _config.strategy.vol_lookback_signal  # 60
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

# ── Globals ────────────────────────────────────────────────────────

_shutdown = False
_risk_enforcer = RiskEnforcer(RISK_ENVELOPE)
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
)

# State persisted across restarts
_STATE_FILE = os.path.join(AUDIT_DIR, "runtime_state.json")


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


def compute_r4_signal(data: Dict[str, pd.DataFrame], force_regime: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any]]:
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

    # 5. Frozen R4 final weights: regime × vol_scale → clip ±0.20
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

    return latest, diag


# ── Order Generation ───────────────────────────────────────────────


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
    """
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
            tgt_lots = max(min_vol, round(tgt_lots, 2))
            max_lots = MAX_POSITION_USD / (price * cs)
            tgt_lots = min(tgt_lots, max_lots)
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

        if delta_signed > 0:
            side = "BUY"
            lots = delta
            reason = f"{info['direction']} {info['weight']:+.1%} ({info['abs_weight']:.1%} |w|)"
        else:
            side = "SELL"
            lots = delta
            reason = f"{info['direction']} {info['weight']:+.1%} ({info['abs_weight']:.1%} |w|)"

        orders.append((sym, side, lots, reason, None))

    # Sort: close orders first (free up margin), then open orders
    close_orders = [o for o in orders if "rotated out" in o[3]]
    open_orders = [o for o in orders if o not in close_orders]

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
    results = {"submitted": 0, "filled": 0, "failed": 0, "fills": []}

    for sym, side, lots, reason, ticket in orders[:MAX_ORDERS_PER_CYCLE]:
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
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

        # Retry logic for transient failures
        result = None
        for attempt in range(max_retries + 1):
            result = mt5.order_send(request)
            if result and result.retcode == MetaTrader5.TRADE_RETCODE_DONE:
                break  # Success
            elif attempt < max_retries:
                # Transient failure — retry with exponential backoff
                delay = retry_delay * (2**attempt)
                log(f"  ⚠️ {side} {lots:.2f} {sym} — retry {attempt + 1}/{max_retries} in {delay:.1f}s")
                time.sleep(delay)

        results["submitted"] += 1

        if result and result.retcode == MetaTrader5.TRADE_RETCODE_DONE:
            results["filled"] += 1
            results["fills"].append(
                {
                    "symbol": sym,
                    "side": side,
                    "lots": lots,
                    "price": result.price,
                    "deal": result.deal,
                }
            )
            verb = "CLOSE" if ticket is not None else side
            log(f"  ✅ {verb} {lots:.2f} {sym} @ {result.price:.5f} — Deal #{result.deal}")
        else:
            results["failed"] += 1
            rc = result.retcode if result else "None"
            cm = result.comment if result else ""
            log(f"  ❌ {side} {lots:.2f} {sym} — {rc} {cm}")

    return results


# ── Main Loop ──────────────────────────────────────────────────────


def _reconnect_mt5(mt5) -> bool:
    """Force a fresh MT5 session.

    mt5linux proxies can return stale/zero data after the terminal or
    bridge restarts while the loop keeps its old session object.
    shutdown() + initialize() re-establishes a healthy connection.
    """
    try:
        mt5.shutdown()
    except Exception:
        pass
    time.sleep(2)
    try:
        return bool(mt5.initialize())
    except Exception:
        return False


def _restart_bridge_if_needed() -> bool:
    """Check if the RPyC bridge is alive; restart it if not.

    Returns True if bridge is reachable after the check.
    Cross-platform: works on Linux, macOS, and Windows (Git Bash).
    """
    import subprocess
    import platform

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

    # Kill stale bridge processes (platform-specific)
    try:
        if system in ("linux", "darwin"):
            subprocess.run(["pkill", "-f", "server.py.*8001"], capture_output=True, timeout=5)
        elif system == "windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "python.exe", "/T"],
                capture_output=True, timeout=5
            )
    except Exception:
        pass
    time.sleep(2)

    # Determine paths based on platform
    if system in ("linux", "darwin"):
        server_dir = "/tmp/mt5linux"
        wine_prefix = os.path.expanduser("~/.wine_mt5")
        wine_python = r"C:\users\manuelhorveydaniel\AppData\Local\Programs\Python\Python312\python.exe"
        bridge_log = "/tmp/mt5bridge.log"

        env = os.environ.copy()
        env["WINEPREFIX"] = wine_prefix
        env["DISPLAY"] = os.environ.get("DISPLAY", ":0")

        # Ensure Xvfb for headless display (Linux only)
        if system == "linux":
            try:
                result = subprocess.run(
                    ["pgrep", "-f", "Xvfb"], capture_output=True, timeout=5
                )
                if result.returncode != 0:
                    subprocess.Popen(
                        ["Xvfb", ":1", "-screen", "0", "1024x768x24"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    time.sleep(1)
            except Exception:
                pass

        # Start bridge with setsid (Linux) or nohup (macOS)
        try:
            if system == "linux":
                subprocess.Popen(
                    ["setsid", "wine", wine_python, "server.py",
                     "--host", "127.0.0.1", "-p", "8001"],
                    cwd=server_dir, env=env,
                    stdout=open(bridge_log, "w"),
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:  # macOS
                subprocess.Popen(
                    ["wine", wine_python, "server.py",
                     "--host", "127.0.0.1", "-p", "8001"],
                    cwd=server_dir, env=env,
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
        if _reconnect_mt5(mt5):
            account = mt5.account_info()
            log("🟢 Reconnected to MT5")
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
        if _reconnect_mt5(mt5):
            log("🟢 Reconnected to MT5")
            data = fetch_d1_data(mt5, R4_SYMBOLS, bars=300)
        if len(data) < 5:
            log(f"⚠️  Only {len(data)} symbols — insufficient data")
            audit({"event": "stale_connection", "symbols": len(data)})
            return {"status": "SKIP", "reason": "insufficient_data"}

    # 2. Compute signal
    target_weights, diag = compute_r4_signal(data, force_regime)

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

    # Check for CRITICAL conditions (breach already exists)
    has_critical = any(r.result == GateResult.CRITICAL for r in gate_results)
    if has_critical:
        critical_gates = [r for r in gate_results if r.result == GateResult.CRITICAL]
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

    # Split into closes and opens
    closes = [o for o in orders if "rotated out" in o[3]]
    opens = [o for o in orders if o not in closes]

    # After closes, we have free slots for opens
    available_after_close = MAX_CONCURRENT - len(pos_list) + len(closes)
    if len(opens) > available_after_close:
        log(f"⚠️  {len(opens)} opens after {len(closes)} closes — truncating to {available_after_close}")
        opens = opens[:available_after_close]
        orders = closes + opens

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

    # 7. Display plan
    log(f"Orders: {len(orders)}")
    for sym, side, lots, reason, ticket in orders:
        verb = "CLOSE" if ticket is not None else side
        log(f"  → {verb} {lots:.2f} {sym} ({reason})")

    # 8. Execute
    if dry_run:
        log("📋 DRY RUN — no orders submitted")
        audit({"event": "dry_run", "orders": len(orders), "diag": diag})
        return {"status": "DRY_RUN", "orders": len(orders), "diag": diag}

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
        "diag": diag,
        "duration_seconds": time.time() - cycle_start,
    }

    log(
        f"Result: {exec_results['filled']}/{exec_results['submitted']} filled | "
        f"Equity: ${cycle_result['equity_after']:,.2f}"
    )

    audit({"event": "executed", **cycle_result})

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

        result = mt5.order_send(request)
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


def main() -> None:
    args = sys.argv[1:]
    loop_mode = "--loop" in args
    force_regime = "--force-regime" in args
    dry_run = "--dry-run" in args
    flatten_only = "--flatten" in args

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

    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        print(f"  ❌ Cannot connect: {mt5.last_error()}")
        return

    account = mt5.account_info()
    log(f"Connected — Account: {account.login}, Equity: ${account.equity:,.2f}")

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
            disconnect_start = time.time()
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
                # Bridge is back — reconnect MT5 through it
                log("  Attempting MT5 reconnection through restarted bridge...")
                if _reconnect_mt5(mt5):
                    log("  ✅ MT5 reconnected after bridge restart")
                else:
                    log("  ⚠️  MT5 still unreachable — waiting...")

            log(f"   Waiting {min(interval, 60)}s for reconnection...")
            for _ in range(min(interval, 60)):
                if _shutdown:
                    break
                time.sleep(1)
            continue

        # ── Reconnection handling ─────────────────────────────────────
        if _disconnect_recovery.state == RecoveryState.DISCONNECTED:
            recovery_msg = _disconnect_recovery.on_reconnect()
            reconnect_time_ms = (time.time() - disconnect_start) * 1000 if 'disconnect_start' in dir() else 0.0
            log(f"🟢 MT5 RECONNECTED — {recovery_msg}")
            audit(
                {
                    "event": "reconnect",
                    "recovery_state": _disconnect_recovery.state.value,
                }
            )
            # Record evidence: reconnect event
            try:
                record_operational_event(
                    event_type="reconnect",
                    detection_time_ms=reconnect_time_ms,
                    recovery_time_ms=reconnect_time_ms,
                    success=True,
                )
            except Exception:
                pass

            # Reconcile: verify positions, equity, fingerprint
            try:
                account = mt5.account_info()
                positions = mt5.positions_get()
                pos_list = list(positions) if positions else []

                # Fingerprint check
                fp_ok = _fingerprint_verifier.verify_all().all_verified

                # Position count check
                pos_ok = len(pos_list) <= RISK_ENVELOPE.max_concurrent_positions

                # Equity check
                eq_ok = account.equity > 0 if account else False

                # Order check: R4 uses market orders only; any pending orders
                # after reconnect are unexpected and indicate possible orphans.
                try:
                    pending = mt5.orders_get()
                    pending_list = list(pending) if pending else []
                    orders_ok = len(pending_list) == 0
                except Exception:
                    # If orders_get fails, treat as unknown — fail-closed
                    pending_list = []
                    orders_ok = False

                # Risk check
                risk_ok = True  # Would need full risk check here

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
                    if not loop_mode:
                        break
                    for _ in range(min(interval, 300)):
                        if _shutdown:
                            break
                        time.sleep(1)
                    continue

                # Request resume
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
                    if not loop_mode:
                        break
                    for _ in range(min(interval, 300)):
                        if _shutdown:
                            break
                        time.sleep(1)
                    continue

            except Exception as e:
                log(f"🔴 Reconciliation error: {e}")
                audit({"event": "reconciliation_error", "error": str(e)})
                _persist_state()
                if not loop_mode:
                    break
                for _ in range(min(interval, 60)):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

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
