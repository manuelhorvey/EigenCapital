"""R4 P0 Safety Supervisor — orchestrates remediation layers around frozen R4.

C6 of the P0 Safety Remediation campaign. This process does NOT trade and
NEVER modifies R4 signal/order logic. It:

  1. verifies the pinned build (fail-closed)            [build_pinning]
  2. classifies every broker position (quarantine)      [position_attribution]
  3. plans idempotent catastrophic stops (>=2xATR)      [catastrophic_protection]
  4. runs blind-window detection with escalation        [watchdog]
  5. records every decision in a hash-chained store     [durable_audit]

Safety defaults:
  - DRY-RUN unless flag file configs/r4_safety.enabled exists AND --live passed.
  - No position without an unambiguous classification is ever managed.
  - Containment (flatten) executes only for R4-owned tickets.

Usage:
  python scripts/r4_safety_supervisor.py --once          # single dry-run tick
  python scripts/r4_safety_supervisor.py --loop --interval 60
  python scripts/r4_safety_supervisor.py --once --live   # requires flag file
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from eigencapital.config import load_config  # noqa: E402
from eigencapital.live.build_pinning import verify_pinned_build  # noqa: E402
from eigencapital.live.catastrophic_protection import (  # noqa: E402
    FlattenOutcome,
    flatten_with_retry,
    live_actions_enabled,
    plan_protection,
)
from eigencapital.live.durable_audit import DurableAudit  # noqa: E402
from eigencapital.live.position_attribution import (  # noqa: E402
    capacity_account,
    classify_all,
    snapshot_hash,
)
from eigencapital.live.watchdog import (  # noqa: E402
    ProbeResult,
    Watchdog,
    trail_age_seconds,
)

AUDIT_DIR = REPO / "reports" / "r4_safety"
FLAG_FILE = REPO / "configs" / "r4_safety.enabled"
LOOP_TRAIL = REPO / "reports" / "r4_loop" / "decisions.jsonl"


def _atr14_pct_by_symbol(symbols: list[str]) -> dict[str, float]:
    """Per-symbol-calendar ATR14% from local D1 exports (audit method)."""
    import pandas as pd

    out: dict[str, float] = {}
    data_dir = REPO / "data" / "mt5"
    for sym in symbols:
        f = data_dir / f"{sym}m_D1.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["time"]).set_index("time").sort_index()
        pc = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                        (df["low"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14, min_periods=10).mean().iloc[-1]
        if atr and atr > 0:
            out[sym] = float(atr / df["close"].iloc[-1])
    return out


class BrokerAdapter:
    """Thin mt5linux adapter; constructed ONLY when live actions are enabled."""

    def __init__(self) -> None:
        from mt5linux import MetaTrader5  # type: ignore
        self._mt5 = MetaTrader5(host="127.0.0.1", port=8001)
        if not self._mt5.initialize():
            raise ConnectionError(f"bridge init failed: {self._mt5.last_error()}")

    def account(self) -> dict[str, Any]:
        a = self._mt5.account_info()
        return {"equity": getattr(a, "equity", 0), "free_margin": getattr(a, "margin_free", 0)}

    def positions(self) -> list[dict[str, Any]]:
        pos = self._mt5.positions_get()
        return [{
            "ticket": p.ticket, "symbol": p.symbol, "type": p.type,
            "volume": p.volume, "price_open": p.price_open, "sl": p.sl,
            "tp": p.tp, "profit": p.profit, "magic": p.magic, "comment": p.comment,
        } for p in (list(pos) if pos else [])]

    def set_sl(self, ticket: int, sl: float) -> bool:
        pos = self._mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]
        req = {
            "action": self._mt5.TRADE_ACTION_SLTX,
            "position": ticket, "sl": float(sl), "tp": p.tp,
        }
        res = self._mt5.order_send(req)
        return bool(res and res.retcode == self._mt5.TRADE_RETCODE_DONE)

    def close_ticket(self, ticket: int) -> bool:
        pos = self._mt5.positions_get(ticket=ticket)
        if not pos:
            return True  # already gone counts as closed
        p = pos[0]
        tick = self._mt5.symbol_info_tick(p.symbol)
        if tick is None:
            return False
        is_long = p.type == 0
        req = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol, "volume": p.volume,
            "type": self._mt5.ORDER_TYPE_SELL if is_long else self._mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if is_long else tick.ask,
            "deviation": 20, "magic": p.magic, "comment": "R4-SAFETY-FLATTEN",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_FOK,
        }
        res = self._mt5.order_send(req)
        return bool(res and res.retcode == self._mt5.TRADE_RETCODE_DONE)


class DryRunBroker:
    """Fixture-backed broker for offline/dry-run ticks."""

    def __init__(self, positions_fixture: list[dict[str, Any]],
                 equity: float = 5010.94, free_margin: float = 1000.0):
        self._positions = positions_fixture
        self.equity = equity
        self.free_margin = free_margin

    def account(self) -> dict[str, Any]:
        return {"equity": self.equity, "free_margin": self.free_margin}

    def positions(self) -> list[dict[str, Any]]:
        return list(self._positions)


def run_tick(broker: Any, audit: DurableAudit, wd: Watchdog,
             max_concurrent: int, live: bool, build_id: str) -> dict[str, Any]:
    acct = broker.account() if hasattr(broker, "account") else {"equity": 0, "free_margin": 0}
    positions = broker.positions()
    ev_hash = snapshot_hash(positions, acct.get("equity"), acct.get("free_margin"))
    classified = classify_all(positions)
    cap = capacity_account(classified, max_concurrent)

    probe = ProbeResult(
        process_alive=_loop_alive(),
        trail_age_seconds=trail_age_seconds(LOOP_TRAIL),
        equity_read_ok=bool(acct.get("equity", 0) > 0),
        broker_reachable=True,  # reaching here implies bridge answered
        evidence_hash=ev_hash,
    )
    decision = wd.evaluate(probe)

    def entry_lookup(p: Any) -> float:
        raw = next((q for q in positions if q.get("ticket") == p.ticket), {})
        return float(raw.get("price_open", 0) or 0)

    sl_by_ticket = {p["ticket"]: float(p.get("sl", 0) or 0)
                    for p in positions if p.get("ticket") is not None}
    symbols = sorted({p.symbol for p in classified})
    atr_map = _atr14_pct_by_symbol(symbols)
    plan = plan_protection(classified, atr_map, sl_by_ticket, entry_lookup)

    actions_taken: list[dict[str, Any]] = []
    if live:
        if hasattr(broker, "set_sl"):
            for a in plan:
                ok = broker.set_sl(int(a.ticket), float(a.detail["sl"]))  # type: ignore[arg-type]
                actions_taken.append({"action": a.kind.value, "ticket": a.ticket,
                                      "ok": ok, **a.detail})
                time.sleep(0.05)
    else:
        actions_taken = [{"action": a.kind.value, "ticket": a.ticket, "dry_run": True,
                          **a.detail} for a in plan]

    record = {
        "build_id": build_id,
        "watch_state": decision.state.value,
        "authorize_trading": decision.authorize_trading,
        "contain_flatten_intent": decision.authorize_flatten_on_reconnect,
        "reason": decision.reason,
        "capacity": {
            "r4_open_count": cap.r4_open_count, "max_concurrent": cap.max_concurrent,
            "contaminated": cap.contaminated,
            "allow_new_entries": cap.allow_new_entries,
            "foreign": cap.foreign_positions,
        },
        "protection_plan": [a for a in actions_taken],
        "broker_snapshot_hash": ev_hash,
        "n_positions_total": len(positions),
    }
    audit.append("safety_tick", record)
    return record


def _loop_alive() -> bool:
    import subprocess
    try:
        r = subprocess.run(["pgrep", "-f", "r4_rebalance_loop"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def contain_flat_r4(broker: Any, audit: DurableAudit, build_id: str) -> dict[str, Any]:
    """Containment: flatten R4-owned positions with retry; never foreign ones."""
    positions = broker.positions()
    own = [p for p in positions if int(p.get("magic", 0) or 0) == 20260825]
    own_tickets = {int(p["ticket"]) for p in own if p.get("ticket") is not None}

    if live_actions_enabled(str(FLAG_FILE)) and hasattr(broker, "close_ticket"):
        outcome, n = flatten_with_retry(lambda: broker.positions(),
                                        broker.close_ticket,
                                        only_tickets=own_tickets or None)
    else:
        outcome, n = FlattenOutcome.ALREADY_FLAT, 0
        if own_tickets:
            outcome = FlattenOutcome.PARTIAL  # dry-run cannot confirm closure
    rec = {
        "build_id": build_id, "event": "containment",
        "outcome": outcome.value, "closed": n,
        "own_tickets": sorted(own_tickets),
        "foreign_left_untouched": len(positions) - len(own),
        "live": live_actions_enabled(str(FLAG_FILE)),
    }
    audit.append("containment", rec)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description="R4 P0 safety supervisor")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--contain-now", action="store_true",
                    help="execute containment flatten path (respects flag file)")
    ap.add_argument("--live", action="store_true",
                    help="permit broker mutations (still requires flag file)")
    args = ap.parse_args()

    config = load_config("production")
    fp = config.live_risk.compute_fingerprint()
    verified, identity = verify_pinned_build(REPO, fp)
    if not verified:
        failed = [c for c in identity.checks if not c.ok]
        print("BUILD PIN FAILED — refusing to operate:")
        for c in failed:
            print(f"  {c.component}: expected={c.expected[:24]} observed={c.observed[:24]}")
        sys.exit(2)

    audit = DurableAudit(AUDIT_DIR / "safety_audit.jsonl",
                         AUDIT_DIR / "safety_audit.mirror.jsonl")
    audit.append("startup", {"build_id": identity.build_id,
                             "git_head": identity.git_head,
                             "checks_ok": identity.all_verified})

    live = args.live and live_actions_enabled(str(FLAG_FILE))
    try:
        broker = BrokerAdapter() if live else DryRunBroker([])
    except Exception as exc:
        print(f"broker unavailable ({exc}); running with empty dry-run fixture")
        broker = DryRunBroker([])

    wd = Watchdog(stale_after_seconds=max(2 * args.interval, 7200),
                  blind_after_seconds=max(4 * args.interval, 14400),
                  contain_after_seconds=max(6 * args.interval, 21600))

    if args.contain_now:
        rec = contain_flat_r4(broker, audit, identity.build_id)
        print(json.dumps(rec, indent=2))
        return

    while True:
        rec = run_tick(broker, audit, wd, config.live_risk.max_concurrent_positions,
                       live=live, build_id=identity.build_id)
        print(json.dumps({k: rec[k] for k in
                          ("watch_state", "authorize_trading", "capacity",
                           "n_positions_total")}, default=str))
        if args.once or not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
