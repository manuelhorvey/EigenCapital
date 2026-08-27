"""Account Readiness — full pre-trading validation against live MT5 state.

Connects to the real MT5 broker, pulls actual account/position/symbol state,
and runs every validator in the pipeline:

  1. Broker connection          (MT5 bridge alive?)
  2. Account identity           (correct login, server, environment?)
  3. Capital boundary           (equity within $5K MINIMAL envelope?)
  4. Symbol universe            (all 15 R4 instruments available?)
  5. Symbol specs               (volume limits, digits, trade permissions?)
  6. Spread / execution         (current spreads within configured bounds?)
  7. Position reconciliation    (classify every open position)
  8. R4 manifest fingerprint    (frozen config unchanged?)
  9. Pre-trading 5-step gate    (the full authorization sequence)

Output: structured GO / NO-GO report with every check result.

Usage:
    python scripts/account_readiness.py
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, "src")

from mt5linux import MetaTrader5


# ── Helpers ────────────────────────────────────────────────────────


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(icon: str, label: str, detail: str = "") -> None:
    suffix = f"  —  {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")


def tick_price(mt5, symbol: str) -> Optional[Dict[str, float]]:
    """Get current bid/ask safely."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {"bid": tick.bid, "ask": tick.ask}


# ── R4 Universe ────────────────────────────────────────────────────

R4_SYMBOLS = [
    "US30",
    "AUDJPY",
    "AUDUSD",
    "AUDCHF",
    "AUDCAD",
    "NZDJPY",
    "GBPJPY",
    "AUDNZD",
    "NZDUSD",
    "NZDCHF",
    "NZDCAD",
    "GBPUSD",
    "GBPCHF",
    "GBPCAD",
    "CHFJPY",
    "EURJPY",
    "USDJPY",
    "CADJPY",
    "XAUUSD",
    "EURUSD",
    "EURCHF",
    "USDCHF",
    "EURCAD",
    "USDCAD",
    "CADCHF",
    "GBPNZD",
    "EURGBP",
    "EURNZD",
    "GBPAUD",
    "EURAUD",
    "BTCUSD",
]

EXPECTED_ACCOUNT_ID = "436921728"
EXPECTED_SERVER = "Exness-MT5Trial9"
EXPECTED_ENVIRONMENT = "demo"  # trial/demo
MAX_EQUITY = 5_100.0  # $5K + 2% buffer for P&L drift
MAX_SPREAD_POINTS = 15  # for forex; metals/crypto/indexes higher


# ── Main ───────────────────────────────────────────────────────────


def main() -> None:
    total_checks = 0
    passed_checks = 0
    critical_failures: List[str] = []

    print("=" * 60)
    print("  ACCOUNT READINESS CHECK")
    print("  Full pre-trading validation against live MT5")
    print("=" * 60)

    # ── 1. Connect to MT5 ──────────────────────────────────────────
    section("1. MT5 CONNECTION")
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    connected = mt5.initialize()
    total_checks += 1
    if not connected:
        check("❌", "MT5 bridge connection", str(mt5.last_error()))
        print("\n  FATAL: Cannot reach MT5 bridge. Aborting.\n")
        mt5.shutdown()
        _summary(total_checks, 0, ["MT5 bridge unreachable"])
        return
    passed_checks += 1
    check("✅", "MT5 bridge connection", "port 8001")

    # ── 2. Account Identity ────────────────────────────────────────
    section("2. ACCOUNT IDENTITY")
    account = mt5.account_info()
    if account is None:
        check("❌", "Account info", "None returned")
        mt5.shutdown()
        _summary(total_checks, passed_checks, ["Cannot read account info"])
        return

    acct_id = str(account.login)
    server = getattr(account, "server", "")
    currency = getattr(account, "currency", "")
    leverage = account.leverage
    balance = account.balance
    equity = account.equity
    free_margin = account.margin_free
    margin = account.margin
    profit = account.profit

    # 2.1 Account ID
    total_checks += 1
    if acct_id == EXPECTED_ACCOUNT_ID:
        passed_checks += 1
        check("✅", "Account ID", acct_id)
    else:
        critical_failures.append(f"Wrong account: {acct_id} != {EXPECTED_ACCOUNT_ID}")
        check("❌", "Account ID", f"expected {EXPECTED_ACCOUNT_ID}, got {acct_id}")

    # 2.2 Server
    total_checks += 1
    if EXPECTED_SERVER.lower() in server.lower():
        passed_checks += 1
        check("✅", "Server", server)
    else:
        critical_failures.append(f"Wrong server: {server}")
        check("❌", "Server", f"expected {EXPECTED_SERVER}, got {server}")

    # 2.3 Currency
    total_checks += 1
    if currency.upper() == "USD":
        passed_checks += 1
        check("✅", "Currency", currency)
    else:
        critical_failures.append(f"Unexpected currency: {currency}")
        check("❌", "Currency", f"expected USD, got {currency}")

    # 2.4 Leverage
    total_checks += 1
    if leverage >= 1:
        passed_checks += 1
        check("✅", "Leverage", f"1:{leverage}")
    else:
        critical_failures.append(f"Invalid leverage: {leverage}")
        check("❌", "Leverage", f"1:{leverage}")

    # ── 3. Capital Boundary ────────────────────────────────────────
    section("3. CAPITAL BOUNDARY ($5K MINIMAL)")

    # 3.1 Equity within max
    total_checks += 1
    if equity <= MAX_EQUITY:
        passed_checks += 1
        check("✅", "Equity within max", f"${equity:,.2f} <= ${MAX_EQUITY:,.0f}")
    else:
        critical_failures.append(f"Equity ${equity:,.2f} exceeds ${MAX_EQUITY:,.0f}")
        check("❌", "Equity within max", f"${equity:,.2f} > ${MAX_EQUITY:,.0f}")

    # 3.2 Positive equity
    total_checks += 1
    if equity > 0:
        passed_checks += 1
        check("✅", "Account funded", f"${equity:,.2f}")
    else:
        critical_failures.append("Account has zero/negative equity")
        check("❌", "Account funded", f"${equity:,.2f}")

    # 3.3 Free margin available
    total_checks += 1
    if free_margin > 0:
        passed_checks += 1
        check("✅", "Free margin", f"${free_margin:,.2f}")
    else:
        critical_failures.append("No free margin")
        check("❌", "Free margin", f"${free_margin:,.2f}")

    # 3.4 Margin utilization
    total_checks += 1
    margin_pct = (margin / equity * 100) if equity > 0 else 100
    if margin_pct <= 50:
        passed_checks += 1
        check("✅", "Margin utilization", f"{margin_pct:.1f}%")
    else:
        critical_failures.append(f"Margin utilization {margin_pct:.1f}% > 50%")
        check("❌", "Margin utilization", f"{margin_pct:.1f}%")

    print(f"\n  Balance:  ${balance:,.2f}")
    print(f"  Equity:   ${equity:,.2f}")
    print(f"  Margin:   ${margin:,.2f}")
    print(f"  Free:     ${free_margin:,.2f}")
    print(f"  P&L:      ${profit:+,.2f}")

    # ── 4. Symbol Universe ─────────────────────────────────────────
    section("4. SYMBOL UNIVERSE (R4 instruments)")
    all_symbols_raw = mt5.symbols_get()
    available_names = {s.name for s in all_symbols_raw} if all_symbols_raw else set()

    missing = [s for s in R4_SYMBOLS if s not in available_names]
    present = [s for s in R4_SYMBOLS if s in available_names]

    total_checks += 1
    if not missing:
        passed_checks += 1
        check("✅", "R4 symbols present", f"{len(present)}/{len(R4_SYMBOLS)}")
    else:
        critical_failures.append(f"Missing R4 symbols: {missing}")
        check("❌", "R4 symbols missing", ", ".join(missing))

    for sym in present:
        check("  ", sym)

    # ── 5. Symbol Specs ────────────────────────────────────────────
    section("5. SYMBOL SPECIFICATIONS")
    spec_issues: List[str] = []
    symbol_data: Dict[str, Dict[str, Any]] = {}

    for sym in R4_SYMBOLS:
        info = mt5.symbol_info(sym)
        if info is None:
            spec_issues.append(f"{sym}: not found")
            continue

        # Enable in market watch
        mt5.symbol_select(sym, True)

        digits = info.digits
        spread = info.spread
        volume_min = info.volume_min
        volume_max = info.volume_max
        trade_mode = info.trade_mode  # 0=disabled, 1=longonly, 2=shortonly, 4=full

        symbol_data[sym] = {
            "digits": digits,
            "spread": spread,
            "volume_min": volume_min,
            "volume_max": volume_max,
            "trade_mode": trade_mode,
        }

        # Check trade permissions
        if trade_mode not in (1, 2, 4):
            spec_issues.append(f"{sym}: trade_mode={trade_mode} (may be disabled)")

        # Check volume
        if volume_min > 1.0:
            spec_issues.append(f"{sym}: volume_min={volume_min} > 1.0")

    total_checks += 1
    if not spec_issues:
        passed_checks += 1
        check("✅", "Symbol specs", f"{len(symbol_data)} symbols validated")
    else:
        for issue in spec_issues:
            critical_failures.append(f"Spec: {issue}")
        check("❌", "Symbol specs", "; ".join(spec_issues))

    # ── 6. Spread / Execution ──────────────────────────────────────
    section("6. SPREAD / EXECUTION CHECK")
    spread_issues: List[str] = []
    spread_data: Dict[str, float] = {}

    for sym in R4_SYMBOLS:
        tick = tick_price(mt5, sym)
        info = mt5.symbol_info(sym)
        if tick is None or info is None:
            spread_issues.append(f"{sym}: no price data")
            continue

        spread_pts = info.spread
        spread_data[sym] = spread_pts

        # Check spread (varies by asset class)
        max_allowed = MAX_SPREAD_POINTS
        if sym in ("XAUUSD", "XAGUSD"):
            max_allowed = 30
        elif sym in ("BTCUSD", "ETHUSD"):
            max_allowed = 500
        elif sym in ("US500", "US30", "USTEC", "USOIL"):
            max_allowed = 50

        if spread_pts > max_allowed:
            spread_issues.append(f"{sym}: {spread_pts} pts (max {max_allowed})")

    total_checks += 1
    if not spread_issues:
        passed_checks += 1
        check("✅", "Spread check", f"{len(spread_data)} symbols within bounds")
    else:
        # Spread issues are WARNING, not CRITICAL (market conditions vary)
        check("⚠️", "Spread warnings", "; ".join(spread_issues))

    # Print spread table
    print()
    print(f"  {'Symbol':<10} {'Spread':>8}")
    print(f"  {'─' * 10} {'─' * 8}")
    for sym in R4_SYMBOLS:
        sp = spread_data.get(sym, 0)
        marker = " ⚠️" if sym in [s.split(":")[0] for s in spread_issues] else ""
        print(f"  {sym:<10} {sp:>6} pts{marker}")

    # ── 7. Position Reconciliation ─────────────────────────────────
    section("7. POSITION RECONCILIATION")
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []

    total_checks += 1
    if len(pos_list) == 0:
        passed_checks += 1
        check("✅", "Clean slate", "0 open positions")
    else:
        check("⚠️", f"Open positions: {len(pos_list)}", "(will be classified)")
        for p in pos_list:
            side = "BUY" if p.type == 0 else "SELL"
            check(
                "  ",
                f"{p.symbol}: {side} {p.volume} @ {p.price_open:.5f} | P&L: ${p.profit:+.4f}",
            )

    # ── 8. R4 Manifest Fingerprint ─────────────────────────────────
    section("8. R4 MANIFEST FINGERPRINT")
    from eigencapital.fidelity.r4_manifest import R4ConfigManifest

    manifest = R4ConfigManifest()
    fp = manifest.compute_identity()

    total_checks += 1
    if fp.startswith("aaab6c00dc05"):
        passed_checks += 1
        check("✅", "Manifest fingerprint", fp[:32] + "...")
    else:
        critical_failures.append(f"Fingerprint drift: {fp[:32]}")
        check("❌", "Manifest fingerprint", f"DRIFT — {fp[:32]}...")

    total_checks += 1
    if manifest.strategy_version == "R4.0":
        passed_checks += 1
        check("✅", "Strategy version", manifest.strategy_version)
    else:
        critical_failures.append(f"Version drift: {manifest.strategy_version}")
        check("❌", "Strategy version", manifest.strategy_version)

    total_checks += 1
    if manifest.data_terminal_id == acct_id:
        passed_checks += 1
        check("✅", "Terminal ID match", f"{manifest.data_terminal_id} == {acct_id}")
    else:
        critical_failures.append(
            f"Terminal ID mismatch: {manifest.data_terminal_id} != {acct_id}"
        )
        check("❌", "Terminal ID match", f"{manifest.data_terminal_id} != {acct_id}")

    # ── 9. Pre-Trading 5-Step Gate ─────────────────────────────────
    section("9. PRE-TRADING 5-STEP GATE")
    from eigencapital.production_qual.pre_trading import (
        PreTradingValidator,
        BrokerStateSnapshot,
    )
    from eigencapital.production_qual.broker_boundary import (
        BrokerBoundaryConfig,
    )

    # Build broker state from real MT5 data
    broker_state = BrokerStateSnapshot(
        account_id=acct_id,
        account_name="EigenCapital-R4-Trial",
        environment=EXPECTED_ENVIRONMENT,
        broker_name="exness",
        platform="mt5",
        equity=equity,
        free_margin=free_margin,
        balance=balance,
        margin_level=(equity / margin * 100) if margin > 0 else 9999.0,
        positions=[
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "profit": p.profit,
            }
            for p in pos_list
        ],
        position_count=len(pos_list),
        available_symbols=sorted(present),
        symbol_specs=symbol_data,
        current_spread=max(spread_data.values()) if spread_data else 0,
        current_slippage=0.0,
        snapshot_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    # Broker boundary config with correct symbol names (no 'm' suffix)
    broker_config = BrokerBoundaryConfig(
        expected_account_id=EXPECTED_ACCOUNT_ID,
        expected_environment=EXPECTED_ENVIRONMENT,
        expected_broker="exness",
        expected_platform="mt5",
        expected_symbols={s: "forex" for s in R4_SYMBOLS[:7]},
    )

    # Run the 5-step validator (without pre-funding gate record)
    validator = PreTradingValidator(
        campaign_id="READINESS-CHECK",
        broker_config=broker_config,
    )

    auth = validator.run_full_validation(
        broker_state=broker_state,
        campaign_boundary=None,  # fresh — no prior campaign
        pre_funding_gate_record=None,  # we skip this step for readiness check
    )

    # Display results
    step_icons = {
        "fund_capital": "💰",
        "connect_broker": "🔌",
        "reconcile": "🔄",
        "validate_fingerprint": "🔐",
        "authorize": "🛡️",
    }

    for check_item in auth.checks:
        step_icon = step_icons.get(check_item.step, "  ")
        icon = (
            "✅"
            if check_item.passed
            else ("❌" if check_item.severity == "CRITICAL" else "⚠️")
        )
        total_checks += 1
        if check_item.passed:
            passed_checks += 1
        elif check_item.severity == "CRITICAL":
            critical_failures.append(
                f"[{check_item.step}] {check_item.check_id}: {check_item.description}"
            )

        detail = ""
        if not check_item.passed:
            detail = f"expected={check_item.expected} observed={check_item.observed}"
        check(
            icon,
            f"{step_icon} [{check_item.step}] {check_item.check_id}: {check_item.description}",
            detail,
        )

    gate_decision = auth.decision
    total_checks += 1
    if gate_decision == "TRADING_AUTHORIZED":
        passed_checks += 1
        check(
            "✅",
            f"Gate decision: {gate_decision}",
            f"{auth.passed_checks}/{auth.total_checks} passed",
        )
    else:
        critical_failures.append(f"Gate decision: {gate_decision}")
        check(
            "❌",
            f"Gate decision: {gate_decision}",
            f"{auth.passed_checks}/{auth.total_checks} passed",
        )

    # Disconnect
    mt5.shutdown()

    # ── FINAL SUMMARY ──────────────────────────────────────────────
    _summary(total_checks, passed_checks, critical_failures)


def _summary(total: int, passed: int, failures: List[str]) -> None:
    failed = total - passed
    print("\n" + "=" * 60)
    print("  ACCOUNT READINESS — FINAL VERDICT")
    print("=" * 60)
    print(f"\n  Checks:  {passed}/{total} passed, {failed} failed")

    if not failures:
        print(f"\n  {'🟢 GO':}")
        print("\n  All checks passed. Account is ready for pre-trading.")
        print("  Next step: run the full PreTradingValidator with")
        print("  pre-funding gate record to get TRADING_AUTHORIZED.\n")
    else:
        print(f"\n  {'🔴 NO-GO'}")
        print("\n  Blocking issues:")
        for f in failures:
            print(f"    ❌ {f}")
        print("\n  DO NOT submit any orders until all issues are resolved.\n")


if __name__ == "__main__":
    main()
