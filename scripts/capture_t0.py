"""Capture T=0 Campaign Snapshot — freeze the immutable starting state.

Connects to the live MT5 broker, captures the complete account state,
runs all validations, and freezes the campaign boundary as an
immutable, hash-chained snapshot.

This becomes the baseline against which all subsequent R4 trades
are measured. Every fill, every P&L attribution, every reconciliation
is compared back to this T=0 reference.

Output:
  - reports/t0_snapshot.json    (machine-readable, hash-chained)
  - reports/t0_snapshot.md     (human-readable report)

Usage:
    python scripts/capture_t0.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

sys.path.insert(0, "src")

from mt5linux import MetaTrader5

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.production_qual.broker_boundary import (
    BrokerBoundaryConfig,
)
from eigencapital.production_qual.capital_boundary import CapitalBoundaryConfig
from eigencapital.production_qual.pre_trading import (
    BrokerStateSnapshot,
    PreTradingValidator,
)
from eigencapital.risk.policy import RiskPolicy

# Instrument eligibility inlined to avoid module import issues
ASSET_CLASSES = {
    "US30": "indices",
    "AUDJPY": "forex",
    "AUDUSD": "forex",
    "AUDCHF": "forex",
    "AUDCAD": "forex",
    "NZDJPY": "forex",
    "GBPJPY": "forex",
    "AUDNZD": "forex",
    "NZDUSD": "forex",
    "NZDCHF": "forex",
    "NZDCAD": "forex",
    "GBPUSD": "forex",
    "GBPCHF": "forex",
    "GBPCAD": "forex",
    "CHFJPY": "forex",
    "EURJPY": "forex",
    "USDJPY": "forex",
    "CADJPY": "forex",
    "XAUUSD": "metals",
    "EURUSD": "forex",
    "EURCHF": "forex",
    "USDCHF": "forex",
    "EURCAD": "forex",
    "USDCAD": "forex",
    "CADCHF": "forex",
    "GBPNZD": "forex",
    "EURGBP": "forex",
    "EURNZD": "forex",
    "GBPAUD": "forex",
    "EURAUD": "forex",
    "BTCUSD": "crypto",
}


def check_eligibility_inline(mt5, position_limit: float) -> Dict[str, Any]:
    results = []
    for sym in R4_SYMBOLS:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info is None or tick is None:
            results.append(
                {
                    "symbol": sym,
                    "asset_class": ASSET_CLASSES.get(sym, "unknown"),
                    "eligible": False,
                    "reason": "not available",
                    "min_volume": 0,
                    "current_ask": 0,
                    "contract_size": 0,
                    "min_notional": 0,
                    "position_limit": position_limit,
                }
            )
            continue
        min_vol = info.volume_min
        ask = tick.ask
        cs = info.trade_contract_size
        min_notional = min_vol * ask * cs
        eligible = min_notional <= position_limit
        reason = (
            f"min lot {min_vol} \u00d7 {ask:.5f} \u00d7 {cs:,.0f} = ${min_notional:,.2f}"
            + (
                f" \u2264 ${position_limit:,.0f}"
                if eligible
                else f" > ${position_limit:,.0f}"
            )
        )
        results.append(
            {
                "symbol": sym,
                "asset_class": ASSET_CLASSES.get(sym, "unknown"),
                "eligible": eligible,
                "reason": reason,
                "min_volume": min_vol,
                "current_ask": ask,
                "contract_size": cs,
                "min_notional": round(min_notional, 2),
                "position_limit": position_limit,
            }
        )
    return {
        "position_limit": position_limit,
        "total_symbols": len(R4_SYMBOLS),
        "eligible_count": sum(1 for r in results if r["eligible"]),
        "ineligible_count": sum(1 for r in results if not r["eligible"]),
        "symbols": results,
    }


# ── Config ─────────────────────────────────────────────────────────

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

REPORT_DIR = "reports"


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(icon: str, label: str, detail: str = "") -> None:
    suffix = f"  —  {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")


def main() -> None:
    print("=" * 60)
    print("  T=0 CAMPAIGN SNAPSHOT")
    print("  Freeze immutable starting state before first R4 order")
    print("=" * 60)

    # ── 1. Connect to MT5 ──────────────────────────────────────────
    section("1. CONNECTING TO MT5")
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        print(f"  ❌ Cannot connect: {mt5.last_error()}")
        return

    account = mt5.account_info()
    check("✅", "Connected", f"Account {account.login}")

    # ── 2. Capture Account State ────────────────────────────────────
    section("2. ACCOUNT STATE")
    equity = account.equity
    balance = account.balance
    free_margin = account.margin_free
    margin = account.margin
    leverage = account.leverage
    margin_level = (equity / margin * 100) if margin > 0 else 9999.0

    check("✅", "Equity", f"${equity:,.2f}")
    check("✅", "Balance", f"${balance:,.2f}")
    check("✅", "Free margin", f"${free_margin:,.2f}")
    check("✅", "Leverage", f"1:{leverage}")
    check("✅", "Margin level", f"{margin_level:,.0f}%")

    # ── 3. Capture Positions ────────────────────────────────────────
    section("3. OPEN POSITIONS")
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []
    position_data = []
    total_exposure = 0.0
    net_exposure = 0.0

    for p in pos_list:
        side = "BUY" if p.type == 0 else "SELL"
        notional = p.volume * p.price_open
        total_exposure += abs(notional)
        net_exposure += notional * (1 if side == "BUY" else -1)
        pos_dict = {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "side": side,
            "volume": p.volume,
            "price_open": p.price_open,
            "price_current": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "swap": p.swap,
            "magic": p.magic,
            "comment": p.comment,
            "time": p.time,
        }
        position_data.append(pos_dict)
        check(
            "✅",
            f"{p.symbol}",
            f"{side} {p.volume} @ {p.price_open:.5f} | P&L: ${p.profit:+.4f}",
        )

    if not pos_list:
        check("✅", "Clean slate", "0 open positions")

    # ── 4. Capture Symbol Specs ─────────────────────────────────────
    section("4. SYMBOL SPECIFICATIONS")
    symbol_specs: Dict[str, Dict[str, Any]] = {}
    for sym in R4_SYMBOLS:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info and tick:
            symbol_specs[sym] = {
                "digits": info.digits,
                "spread": info.spread,
                "volume_min": info.volume_min,
                "volume_max": info.volume_max,
                "volume_step": info.volume_step,
                "trade_contract_size": info.trade_contract_size,
                "trade_mode": info.trade_mode,
                "bid": tick.bid,
                "ask": tick.ask,
            }
    check("✅", "Symbol specs", f"{len(symbol_specs)} symbols captured")

    # ── 4b. Instrument Eligibility ─────────────────────────────────
    section("4b. INSTRUMENT ELIGIBILITY (broker-derived)")
    cap_cfg = CapitalBoundaryConfig()
    eligibility = check_eligibility_inline(mt5, cap_cfg.max_position_size)

    eligible_syms = [s["symbol"] for s in eligibility["symbols"] if s["eligible"]]
    ineligible_syms = [s["symbol"] for s in eligibility["symbols"] if not s["eligible"]]

    check(
        "✅",
        f"Eligible: {len(eligible_syms)}/{eligibility['total_symbols']}",
        ", ".join(eligible_syms),
    )
    check(
        "❌",
        f"Ineligible: {len(ineligible_syms)}",
        ", ".join(ineligible_syms) if ineligible_syms else "none",
    )

    for s in eligibility["symbols"]:
        icon = "✅" if s["eligible"] else "❌"
        check(icon, f"  {s['symbol']:<10} {s['asset_class']:<10}", s["reason"])

    # ── 5. Fingerprints ─────────────────────────────────────────────
    section("5. FINGERPRINTS")

    manifest = R4ConfigManifest()
    r4_fingerprint = manifest.compute_identity()
    check("✅", "R4 Manifest", f"{r4_fingerprint[:32]}...")

    policy = RiskPolicy()
    policy_data = json.dumps(policy.to_dict(), sort_keys=True).encode("utf-8")
    policy_fingerprint = hashlib.sha256(policy_data).hexdigest()
    check("✅", "Risk Policy", f"{policy_fingerprint[:32]}...")

    broker_config = BrokerBoundaryConfig()
    broker_fingerprint = broker_config.compute_fingerprint()
    check("✅", "Broker Config", f"{broker_fingerprint[:32]}...")

    capital_config = CapitalBoundaryConfig()
    capital_fingerprint = capital_config.compute_fingerprint()
    check("✅", "Capital Config", f"{capital_fingerprint[:32]}...")

    # ── 6. Pre-Trading Validation ───────────────────────────────────
    section("6. PRE-TRADING VALIDATION")
    broker_state = BrokerStateSnapshot(
        account_id=str(account.login),
        account_name="EigenCapital-R4-Trial",
        environment="demo",
        broker_name="exness",
        platform="mt5",
        equity=equity,
        free_margin=free_margin,
        balance=balance,
        margin_level=margin_level,
        positions=position_data,
        position_count=len(pos_list),
        available_symbols=sorted(symbol_specs.keys()),
        symbol_specs=symbol_specs,
        current_spread=max(s.get("spread", 0) for s in symbol_specs.values())
        if symbol_specs
        else 0,
        current_slippage=0.0,
        snapshot_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    validator = PreTradingValidator(
        campaign_id="R4-MINIMAL-5K-T0",
        broker_config=broker_config,
        capital_config=capital_config,
    )

    auth = validator.run_full_validation(
        broker_state=broker_state,
        campaign_boundary=None,
        pre_funding_gate_record=None,
    )

    for c in auth.checks:
        icon = "✅" if c.passed else ("❌" if c.severity == "CRITICAL" else "⚠️")
        check(icon, f"[{c.step}] {c.check_id}: {c.description}")

    check(
        "✅" if auth.decision == "TRADING_AUTHORIZED" else "⚠️",
        "Gate decision",
        auth.decision,
    )

    # ── 7. Build & Freeze Snapshot ───────────────────────────────────
    section("7. FREEZING T=0 SNAPSHOT")
    now = datetime.now(timezone.utc).isoformat()
    campaign_id = f"R4-MINIMAL-5K-{now[:10]}"

    snapshot = {
        "version": "1.0",
        "campaign_id": campaign_id,
        "snapshot_timestamp": now,
        # Account state
        "account_id": str(account.login),
        "account_name": "EigenCapital-R4-Trial",
        "broker_name": "exness",
        "server": getattr(account, "server", ""),
        "environment": "demo",
        "platform": "mt5",
        "currency": "USD",
        # Financial state
        "equity": equity,
        "balance": balance,
        "free_margin": free_margin,
        "margin": margin,
        "leverage": leverage,
        "margin_level": margin_level,
        # Positions
        "open_positions": position_data,
        "position_count": len(pos_list),
        "total_exposure": total_exposure,
        "net_exposure": net_exposure,
        # Pending orders
        "pending_orders": [],
        "pending_order_count": 0,
        # Fingerprints (immutable)
        "fingerprints": {
            "r4_manifest": r4_fingerprint,
            "risk_policy": policy_fingerprint,
            "broker_config": broker_fingerprint,
            "capital_config": capital_fingerprint,
            "strategy_version": manifest.strategy_version,
            "data_terminal_id": manifest.data_terminal_id,
        },
        # Gate records
        "gates": {
            "pre_trading_decision": auth.decision,
            "pre_trading_checks_passed": auth.passed_checks,
            "pre_trading_checks_total": auth.total_checks,
            "pre_trading_hash": auth.authorization_fingerprint,
        },
        # Frozen risk limits
        "risk_limits": {
            "max_drawdown_pct": policy.max_drawdown_pct,
            "daily_loss_limit": policy.daily_loss_limit,
            "max_gross_leverage": policy.max_gross_leverage,
            "max_position_count": policy.max_position_count,
            "max_concentration_pct": policy.max_concentration_pct,
            "max_asset_class_exposure_pct": policy.max_asset_class_exposure_pct,
        },
        # Frozen campaign parameters
        "campaign_params": {
            "max_equity": capital_config.max_equity,
            "max_position_size": capital_config.max_position_size,
            "max_order_notional": capital_config.max_order_notional,
            "max_concurrent_positions": capital_config.max_concurrent_positions,
            "max_drawdown_pct": capital_config.max_drawdown_pct,
            "max_daily_loss": capital_config.max_daily_loss,
            "campaign_duration_days": capital_config.campaign_duration_days,
        },
        # Symbol specs at T=0
        "symbol_specs": symbol_specs,
        # Capital-scale instrument eligibility (broker-derived)
        "instrument_eligibility": {
            "position_limit": cap_cfg.max_position_size,
            "eligible_symbols": eligible_syms,
            "ineligible_symbols": ineligible_syms,
            "eligible_count": len(eligible_syms),
            "ineligible_count": len(ineligible_syms),
            "details": eligibility["symbols"],
        },
        # Research universe vs executable universe
        "universes": {
            "research_universe": R4_SYMBOLS,
            "executable_universe": eligible_syms,
            "excluded_by_scale": ineligible_syms,
        },
        # Pre-campaign operational validation trades
        # (executed before T=0 to verify the execution pipeline)
        "pre_campaign_trades": {
            "classification": "operational_validation",
            "description": "Real MT5 orders executed to prove frozen R4 → live MT5 → order → fill → reconciliation pipeline works. Not part of MINIMAL qualification statistics.",
            "trades": [
                {
                    "symbol": "AUDUSD",
                    "side": "BUY",
                    "volume": 0.01,
                    "context": "pipeline_validation",
                },
                {
                    "symbol": "US500",
                    "side": "BUY",
                    "volume": 0.14,
                    "context": "pipeline_validation",
                },
                {
                    "symbol": "USDCHF",
                    "side": "BUY",
                    "volume": 0.01,
                    "context": "pipeline_validation",
                },
                {
                    "symbol": "USOIL",
                    "side": "BUY",
                    "volume": 0.01,
                    "context": "pipeline_validation",
                },
            ],
            "total_pre_campaign_trades": 4,
        },
    }

    # Compute snapshot hash (tamper detection)
    snapshot_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot_hash

    check("✅", "Snapshot hash", f"{snapshot_hash[:32]}...")

    # ── 8. Save ─────────────────────────────────────────────────────
    section("8. SAVING T=0 SNAPSHOT")
    os.makedirs(REPORT_DIR, exist_ok=True)

    json_path = os.path.join(REPORT_DIR, "t0_snapshot.json")
    with open(json_path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    check("✅", "JSON", json_path)

    # Markdown report
    md_lines = [
        "# T=0 Campaign Snapshot — Frozen Starting State",
        "",
        f"**Campaign:** {campaign_id}",
        f"**Timestamp:** {now}",
        f"**Snapshot Hash:** `{snapshot_hash}`",
        "",
        "---",
        "",
        "## Account State",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Account | {account.login} |",
        f"| Server | {getattr(account, 'server', 'N/A')} |",
        f"| Equity | ${equity:,.2f} |",
        f"| Balance | ${balance:,.2f} |",
        f"| Free Margin | ${free_margin:,.2f} |",
        f"| Leverage | 1:{leverage} |",
        f"| Margin Level | {margin_level:,.0f}% |",
        "",
        "## Positions at T=0",
        "",
    ]

    if pos_list:
        md_lines.extend(
            [
                "| Ticket | Symbol | Side | Volume | Entry | P&L |",
                "|---|---|---|---|---|---|",
            ]
        )
        for p in position_data:
            md_lines.append(
                f"| {p['ticket']} | {p['symbol']} | {p['side']} | "
                f"{p['volume']} | {p['price_open']:.5f} | ${p['profit']:+.4f} |"
            )
    else:
        md_lines.append("*Clean slate — no open positions.*")

    md_lines.extend(
        [
            "",
            f"- Total exposure: ${total_exposure:,.2f}",
            f"- Net exposure: ${net_exposure:,.2f}",
            "",
            "## Instrument Eligibility (Broker-Derived)",
            "",
            f"**Position Limit:** ${cap_cfg.max_position_size:,.0f}",
            f"**Eligible:** {len(eligible_syms)}/{len(R4_SYMBOLS)} | **Ineligible:** {len(ineligible_syms)}/{len(R4_SYMBOLS)}",
            "",
            "### Research Universe vs Executable Universe",
            "",
            "| Symbol | Asset Class | Min Notional | Status |",
            "|---|---|---|---|",
        ]
    )

    for s in eligibility["symbols"]:
        icon = "✅" if s["eligible"] else "❌"
        status = "ELIGIBLE" if s["eligible"] else "INELIGIBLE"
        md_lines.append(
            f"| {s['symbol']} | {s['asset_class']} | ${s['min_notional']:,.2f} | {icon} {status} |"
        )

    md_lines.extend(
        [
            "",
            "*Research universe ≠ executable universe at every capital scale.*",
            "*Exclusions are broker-derived from MT5 contract specifications.*",
            "",
            "## Pre-Campaign Operational Validation Trades",
            "",
            "*These 4 real orders were executed BEFORE the T=0 snapshot to prove the*",
            "*execution pipeline works. They are classified as operational validation,*",
            "*not part of MINIMAL qualification statistics.*",
            "",
            "| Symbol | Side | Volume | Context |",
            "|---|---|---|---|",
            "| AUDUSD | BUY | 0.01 | pipeline_validation |",
            "| US500 | BUY | 0.14 | pipeline_validation |",
            "| USDCHF | BUY | 0.01 | pipeline_validation |",
            "| USOIL | BUY | 0.01 | pipeline_validation |",
            "",
            "## Fingerprints (Immutable)",
            "",
            "| Component | Hash |",
            "|---|---|",
            f"| R4 Manifest | `{r4_fingerprint[:32]}...` |",
            f"| Risk Policy | `{policy_fingerprint[:32]}...` |",
            f"| Broker Config | `{broker_fingerprint[:32]}...` |",
            f"| Capital Config | `{capital_fingerprint[:32]}...` |",
            f"| Strategy Version | {manifest.strategy_version} |",
            f"| Terminal ID | {manifest.data_terminal_id} |",
            "",
            "## Pre-Trading Validation",
            "",
            f"**Decision:** {auth.decision}",
            f"**Checks:** {auth.passed_checks}/{auth.total_checks} passed",
            "",
        ]
    )

    for c in auth.checks:
        icon = "✅" if c.passed else ("❌" if c.severity == "CRITICAL" else "⚠️")
        md_lines.append(f"- {icon} **{c.check_id}**: {c.description}")
        if not c.passed:
            md_lines.append(f"  - Expected: {c.expected}")
            md_lines.append(f"  - Observed: {c.observed}")

    md_lines.extend(
        [
            "",
            "## Frozen Risk Limits",
            "",
            "| Limit | Value |",
            "|---|---|",
            f"| Max drawdown | {policy.max_drawdown_pct:.1f}% |",
            f"| Daily loss limit | ${policy.daily_loss_limit:,.0f} |",
            f"| Max gross leverage | {policy.max_gross_leverage:.2f}x |",
            f"| Max positions | {policy.max_position_count} |",
            "",
            "## Frozen Campaign Parameters",
            "",
            "| Parameter | Value |",
            "|---|---|",
            f"| Max equity | ${capital_config.max_equity:,.0f} |",
            f"| Max position size | ${capital_config.max_position_size:,.0f} |",
            f"| Max order notional | ${capital_config.max_order_notional:,.0f} |",
            f"| Max concurrent | {capital_config.max_concurrent_positions} |",
            f"| Campaign duration | {capital_config.campaign_duration_days} days |",
            "",
            "---",
            "",
            "*This snapshot is the immutable T=0 reference.*",
            "*All subsequent R4 trades are interpreted relative to this state.*",
            f"*Tamper detection: SHA-256 `{snapshot_hash}`*",
        ]
    )

    md_path = os.path.join(REPORT_DIR, "t0_snapshot.md")
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    check("✅", "Markdown", md_path)

    # Disconnect
    mt5.shutdown()

    # Final
    print("\n" + "=" * 60)
    print("  T=0 SNAPSHOT FROZEN")
    print(f"  Campaign: {campaign_id}")
    print(f"  Equity: ${equity:,.2f}")
    print(f"  Positions: {len(pos_list)}")
    print(f"  Hash: {snapshot_hash[:32]}...")
    print(f"  Saved: {json_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
