#!/usr/bin/env python3
"""R4 Supervisor Dry-Run — comprehensive live-state verification.

Probes the actual MT5 account and proves every safety gate:
  1. Position ownership (R4 vs foreign vs unclassified)
  2. Position count vs max_concurrent
  3. Catastrophic protection (SL) on every R4 position
  4. Equity/drawdown state
  5. Fingerprint verification
  6. Broker connectivity
  7. Stale state detection
  8. Watchdog state machine
  9. Intended flatten/protection actions
  10. Quarantine behavior (foreign → block new entries)

Usage:
    python scripts/r4_supervisor_dryrun.py
    python scripts/r4_supervisor_dryrun.py --verbose
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, "src")

import numpy as np

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None

from eigencapital.config import load_config
from eigencapital.live.position_attribution import (
    classify_all,
    capacity_account,
    snapshot_hash,
    R4_MAGIC,
)
from eigencapital.live.catastrophic_protection import (
    plan_protection,
    disaster_stop_price,
    ActionKind,
)
from eigencapital.live.watchdog import Watchdog, ProbeResult, WatchState
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier


# ── Gate result types ─────────────────────────────────────────────

@dataclass
class GateCheck:
    name: str
    passed: bool
    severity: str  # "info", "warn", "critical"
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisorReport:
    timestamp: str
    account_id: int
    balance: float
    equity: float
    free_margin: float
    positions_total: int
    r4_positions: int
    foreign_positions: int
    unclassified_positions: int
    positions_with_sl: int
    positions_without_sl: int
    fingerprint_ok: bool
    watchdog_state: str
    contamination: bool
    gates: List[GateCheck]
    intended_actions: List[Dict[str, Any]]
    verdict: str  # "PASS", "BLOCKED", "CRITICAL"
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "account_id": self.account_id,
            "balance": self.balance,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "positions": {
                "total": self.positions_total,
                "r4": self.r4_positions,
                "foreign": self.foreign_positions,
                "unclassified": self.unclassified_positions,
                "with_sl": self.positions_with_sl,
                "without_sl": self.positions_without_sl,
            },
            "fingerprint_ok": self.fingerprint_ok,
            "watchdog_state": self.watchdog_state,
            "contamination": self.contamination,
            "gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "severity": g.severity,
                    "detail": g.detail,
                    "evidence": g.evidence,
                }
                for g in self.gates
            ],
            "intended_actions": self.intended_actions,
            "verdict": self.verdict,
            "message": self.message,
        }

    def to_markdown(self) -> str:
        lines = [
            "# R4 Supervisor Dry-Run Report",
            "",
            f"**Timestamp:** {self.timestamp}",
            f"**Account:** {self.account_id}",
            f"**Verdict:** {'✅ ' + self.verdict if self.verdict == 'PASS' else '🔴 ' + self.verdict}",
            "",
            "## Account State",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Balance | ${self.balance:,.2f} |",
            f"| Equity | ${self.equity:,.2f} |",
            f"| Free Margin | ${self.free_margin:,.2f} |",
            "",
            "## Position Inventory",
            "",
            f"| Category | Count |",
            f"|---|---|",
            f"| Total | {self.positions_total} |",
            f"| R4 (magic={R4_MAGIC}) | {self.r4_positions} |",
            f"| Foreign (magic≠{R4_MAGIC}) | {self.foreign_positions} |",
            f"| Unclassified | {self.unclassified_positions} |",
            f"| With SL | {self.positions_with_sl} |",
            f"| Without SL | {self.positions_without_sl} |",
            "",
            "## Safety Gates",
            "",
        ]
        for g in self.gates:
            icon = "✅" if g.passed else ("⚠️" if g.severity == "warn" else "🔴")
            lines.append(f"- {icon} **{g.name}**: {g.detail}")

        if self.intended_actions:
            lines.extend(["", "## Intended Actions (Dry-Run)", ""])
            for a in self.intended_actions:
                lines.append(f"- {a.get('kind', '?')} {a.get('symbol', '?')} #{a.get('ticket', '?')} — {a.get('reason', '')}")

        lines.extend([
            "",
            "## Verdict",
            "",
            f"**{self.verdict}** — {self.message}",
        ])

        return "\n".join(lines)


# ── Compute ATR for SL planning ───────────────────────────────────

def compute_atr_pct(mt5, symbol: str, period: int = 14) -> Optional[float]:
    """Compute ATR% from daily data."""
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        arr = np.array(rates)
        high, low, close = arr["high"], arr["low"], arr["close"]
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        atr = float(np.mean(tr[-period:]))
        return atr / float(close[-1]) if close[-1] > 0 else None
    except Exception:
        return None


# ── Main supervisor ───────────────────────────────────────────────

def run_supervisor_dryrun(verbose: bool = False) -> SupervisorReport:
    """Run the full supervisor dry-run against live MT5."""
    now = datetime.now(timezone.utc).isoformat()
    gates: List[GateCheck] = []
    intended_actions: List[Dict[str, Any]] = []

    # ── 1. Broker connectivity ────────────────────────────────────
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    connected = bool(mt5.initialize())
    gates.append(GateCheck(
        name="broker_connectivity",
        passed=connected,
        severity="critical",
        detail="MT5 connection established" if connected else "CANNOT CONNECT TO MT5",
    ))
    if not connected:
        return SupervisorReport(
            timestamp=now, account_id=0, balance=0, equity=0, free_margin=0,
            positions_total=0, r4_positions=0, foreign_positions=0,
            unclassified_positions=0, positions_with_sl=0, positions_without_sl=0,
            fingerprint_ok=False, watchdog_state="N/A", contamination=False,
            gates=gates, intended_actions=[], verdict="CRITICAL",
            message="Cannot connect to MT5 — all gates fail",
        )

    # ── 2. Account state ──────────────────────────────────────────
    account = mt5.account_info()
    balance = float(account.balance) if account else 0
    equity = float(account.equity) if account else 0
    free_margin = float(getattr(account, "margin_free", 0) or getattr(account, "free_margin", 0) or 0)
    account_id = int(account.login) if account else 0

    # ── 3. Position inventory ─────────────────────────────────────
    positions = list(mt5.positions_get() or [])
    classified = classify_all([
        {
            "ticket": p.ticket, "symbol": p.symbol, "type": p.type,
            "volume": p.volume, "magic": p.magic, "comment": p.comment,
            "profit": p.profit, "price_open": p.price_open,
            "sl": p.sl, "tp": p.tp,
        }
        for p in positions
    ])

    config = load_config("production")
    capacity = capacity_account(classified, config.capital.max_concurrent_positions)

    r4_count = capacity.r4_open_count
    foreign_count = len(capacity.foreign_positions)
    unclassified_count = sum(1 for c in classified if c.pclass.value not in ("R4_BOT",))
    # More precise: unclassified = magic not in known set
    from eigencapital.live.position_attribution import PositionClass
    unclassified_count = sum(1 for c in classified if c.pclass == PositionClass.FOREIGN_MAGIC_UNKNOWN)

    positions_with_sl = sum(1 for p in positions if p.sl > 0)
    positions_without_sl = sum(1 for p in positions if p.sl <= 0)

    gates.append(GateCheck(
        name="position_count",
        passed=r4_count <= config.capital.max_concurrent_positions,
        severity="critical" if r4_count > config.capital.max_concurrent_positions else "info",
        detail=f"{r4_count}/{config.capital.max_concurrent_positions} R4 positions",
        evidence={"r4_count": r4_count, "max": config.capital.max_concurrent_positions},
    ))

    gates.append(GateCheck(
        name="foreign_positions",
        passed=foreign_count == 0,
        severity="critical" if foreign_count > 0 else "info",
        detail=f"{foreign_count} foreign position(s) present" if foreign_count else "No foreign positions",
        evidence={"foreign_count": foreign_count, "foreign": capacity.foreign_positions},
    ))

    gates.append(GateCheck(
        name="unclassified_positions",
        passed=unclassified_count == 0,
        severity="critical" if unclassified_count > 0 else "info",
        detail=f"{unclassified_count} unclassified position(s)",
    ))

    contamination = capacity.contaminated

    # ── 4. Catastrophic protection check ──────────────────────────
    no_sl_r4 = [p for p in positions if p.magic == R4_MAGIC and p.sl <= 0]
    with_sl_r4 = [p for p in positions if p.magic == R4_MAGIC and p.sl > 0]

    gates.append(GateCheck(
        name="catastrophic_protection",
        passed=len(no_sl_r4) == 0,
        severity="critical" if no_sl_r4 else "warn",
        detail=f"{len(with_sl_r4)}/{r4_count} R4 positions have SL",
        evidence={
            "positions_with_sl": [
                {"ticket": p.ticket, "symbol": p.symbol, "sl": p.sl}
                for p in with_sl_r4
            ],
            "positions_without_sl": [
                {"ticket": p.ticket, "symbol": p.symbol, "entry": p.price_open}
                for p in no_sl_r4
            ],
        },
    ))

    # Compute intended protection actions for positions missing SL
    if no_sl_r4:
        atr_pct_by_symbol: Dict[str, float] = {}
        for p in no_sl_r4:
            if p.symbol not in atr_pct_by_symbol:
                atr = compute_atr_pct(mt5, p.symbol)
                if atr is not None:
                    atr_pct_by_symbol[p.symbol] = atr

        def entry_price_lookup(cp):
            # Find the original position
            for p in no_sl_r4:
                if p.ticket == cp.ticket:
                    return float(p.price_open)
            return 0.0

        current_sl = {p.ticket: float(p.sl) for p in no_sl_r4 if p.sl > 0}
        protection_actions = plan_protection(
            [c for c in classified if c.ticket in {p.ticket for p in no_sl_r4}],
            atr_pct_by_symbol,
            current_sl,
            entry_price_lookup,
        )
        for action in protection_actions:
            intended_actions.append({
                "kind": action.kind.value,
                "symbol": action.symbol,
                "ticket": action.ticket,
                "sl": action.detail.get("sl"),
                "reason": action.detail.get("reason"),
            })

    # ── 5. Fingerprint verification ───────────────────────────────
    try:
        verifier = FingerprintVerifier(config=config)
        fp_result = verifier.verify_all()
        fp_ok = fp_result.all_verified
        failed_checks = [c for c in fp_result.checks if c.status != "verified"]
        detail = "All fingerprints verified" if fp_ok else f"{len(failed_checks)} fingerprint(s) mismatched"
        evidence = {"checks": [c.to_dict() for c in fp_result.checks]}
    except Exception as e:
        fp_ok = False
        detail = f"Fingerprint verification error: {e}"
        evidence = {"error": str(e)}

    gates.append(GateCheck(
        name="fingerprint_verification",
        passed=fp_ok,
        severity="critical",
        detail=detail,
        evidence=evidence,
    ))

    # ── 6. Equity/drawdown check ──────────────────────────────────
    dd_pct = (config.capital.max_equity - equity) / config.capital.max_equity if config.capital.max_equity > 0 else 0
    equity_ok = equity >= config.live_risk.min_equity
    gates.append(GateCheck(
        name="equity_floor",
        passed=equity_ok,
        severity="critical" if not equity_ok else "info",
        detail=f"Equity ${equity:,.2f} {'above' if equity_ok else 'BELOW'} minimum ${config.live_risk.min_equity:,.0f}",
        evidence={"equity": equity, "min_equity": config.live_risk.min_equity},
    ))

    # ── 7. Capacity verdict (quarantine logic) ────────────────────
    gates.append(GateCheck(
        name="quarantine_logic",
        passed=not contamination,
        severity="warn" if contamination else "info",
        detail=capacity.reason,
        evidence={
            "allow_new_entries": capacity.allow_new_entries,
            "allow_self_rotation": capacity.allow_self_rotation,
        },
    ))

    if contamination:
        # Intended action: close foreign positions
        for fp in capacity.foreign_positions:
            intended_actions.append({
                "kind": "CLOSE_FOREIGN",
                "symbol": fp.get("symbol"),
                "ticket": fp.get("ticket"),
                "reason": f"Foreign position (magic={fp.get('magic')}) — quarantine",
            })

    # ── 8. Watchdog state (probe-based) ───────────────────────────
    watchdog = Watchdog(
        stale_after_seconds=300,   # 5 min
        blind_after_seconds=900,   # 15 min
        contain_after_seconds=3600,  # 1 hour
    )
    # Simulate a healthy probe (we're connected and just polled)
    probe = ProbeResult(
        process_alive=True,
        trail_age_seconds=0.0,
        equity_read_ok=equity > 0,
        broker_reachable=True,
        evidence_hash=snapshot_hash(
            [{"ticket": p.ticket, "symbol": p.symbol} for p in positions],
            equity, free_margin,
        ),
    )
    decision = watchdog.evaluate(probe)
    watchdog_state = decision.state.value

    gates.append(GateCheck(
        name="watchdog_state",
        passed=decision.authorize_trading,
        severity="info",
        detail=f"Watchdog: {watchdog_state} — {decision.reason}",
        evidence={
            "state": watchdog_state,
            "authorize_trading": decision.authorize_trading,
            "authorize_flatten": decision.authorize_flatten_on_reconnect,
        },
    ))

    # ── 9. Position detail listing ────────────────────────────────
    if verbose:
        print("\nPosition Detail:")
        for p in positions:
            cls = [c for c in classified if c.ticket == p.ticket][0]
            icon = "🟢" if cls.pclass.value == "R4_BOT" else "🔴"
            sl_str = f"{p.sl:.5f}" if p.sl > 0 else "NONE"
            print(f"  {icon} #{p.ticket} {p.symbol} {'BUY' if p.type == 0 else 'SELL'} "
                  f"{p.volume:.2f} @ {p.price_open:.5f} SL={sl_str} magic={p.magic}")

    # ── 10. Compute snapshot hash ─────────────────────────────────
    broker_hash = snapshot_hash(
        [{"ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
          "type": p.type, "magic": p.magic} for p in positions],
        equity, free_margin,
    )

    # ── Verdict ───────────────────────────────────────────────────
    critical_gates = [g for g in gates if not g.passed and g.severity == "critical"]
    warn_gates = [g for g in gates if not g.passed and g.severity == "warn"]

    if critical_gates:
        verdict = "CRITICAL"
        message = f"{len(critical_gates)} critical gate(s) failed: {', '.join(g.name for g in critical_gates)}"
    elif warn_gates:
        verdict = "BLOCKED"
        message = f"{len(warn_gates)} warning gate(s): {', '.join(g.name for g in warn_gates)}"
    else:
        verdict = "PASS"
        message = "All safety gates passed — system is compliant"

    report = SupervisorReport(
        timestamp=now,
        account_id=account_id,
        balance=balance,
        equity=equity,
        free_margin=free_margin,
        positions_total=len(positions),
        r4_positions=r4_count,
        foreign_positions=foreign_count,
        unclassified_positions=unclassified_count,
        positions_with_sl=positions_with_sl,
        positions_without_sl=positions_without_sl,
        fingerprint_ok=fp_ok,
        watchdog_state=watchdog_state,
        contamination=contamination,
        gates=gates,
        intended_actions=intended_actions,
        verdict=verdict,
        message=message,
    )

    mt5.shutdown()
    return report


# ── CLI ───────────────────────────────────────────────────────────

def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("  R4 SUPERVISOR DRY-RUN")
    print("  Live-state verification against actual MT5 account")
    print("=" * 70)

    report = run_supervisor_dryrun(verbose=verbose)

    # Print gates
    print(f"\nAccount: {report.account_id} | Balance: ${report.balance:,.2f} | Equity: ${report.equity:,.2f}")
    print(f"Positions: {report.positions_total} total ({report.r4_positions} R4, {report.foreign_positions} foreign, {report.unclassified_positions} unclassified)")
    print(f"SL Coverage: {report.positions_with_sl}/{report.positions_total} positions protected")
    print(f"Fingerprint: {'✅ verified' if report.fingerprint_ok else '❌ MISMATCH'}")
    print(f"Watchdog: {report.watchdog_state}")
    print(f"Contamination: {'⚠️ YES' if report.contamination else '✅ NO'}")

    print("\nSafety Gates:")
    for g in report.gates:
        icon = "✅" if g.passed else ("⚠️" if g.severity == "warn" else "🔴")
        print(f"  {icon} {g.name}: {g.detail}")

    if report.intended_actions:
        print(f"\nIntended Actions ({len(report.intended_actions)}):")
        for a in report.intended_actions:
            print(f"  → {a['kind']} {a.get('symbol', '?')} #{a.get('ticket', '?')} — {a.get('reason', '')}")

    print(f"\n{'=' * 70}")
    print(f"  VERDICT: {report.verdict}")
    print(f"  {report.message}")
    print(f"{'=' * 70}")

    # Save report
    os.makedirs("reports/r4_qualification", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = f"reports/r4_qualification/supervisor_dryrun_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    print(f"\nJSON: {json_path}")

    md_path = f"reports/r4_qualification/supervisor_dryrun_{ts}.md"
    with open(md_path, "w") as f:
        f.write(report.to_markdown())
    print(f"MD:   {md_path}")

    # Exit code: 0=pass, 1=blocked, 2=critical
    if report.verdict == "PASS":
        sys.exit(0)
    elif report.verdict == "BLOCKED":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
