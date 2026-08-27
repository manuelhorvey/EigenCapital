"""Phases 10-13 artifacts: live comparison, survival synthesis, scaling, profitability."""

from __future__ import annotations

import json
import sys
from math import erf, log, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports" / "r4_economics_audit"
sys.path.insert(0, str(REPO / "scripts" / "audit"))
sys.path.insert(0, str(REPO / "src"))


def jdump(obj, name):
    (OUT / name).write_text(json.dumps(obj, indent=2, default=str))
    print("wrote", name)


def phase10_live_comparison() -> None:
    deals = json.load(open(OUT / "mt5_deals_live.json"))
    bot = [d for d in deals if d.get("magic") == 20260825]
    comp = {
        "evidence_window": "2026-08-25T12:31Z .. 2026-08-26T01:07Z (~12.5h)",
        "fills_observed_bot": len(bot),
        "fill_rate_reported": "all executed events fully filled (6/6,1/1,8/8,8/8,8/8,8/8)",
        "cycle_duration_seconds_first_cycle": 2.74,
        "swap_charged_total": float(sum(d.get("swap", 0) for d in deals)),
        "commission_charged_total": float(sum(d.get("commission", 0) for d in deals)),
        "cost_model_reconciliation": {
            "config_transaction_cost_bps": 10.0,
            "config_slippage_bps": 5.0,
            "live_swap_commission": 0.0,
            "note": (
                "trial account zero swap/commission; true cost is spread crossing; "
                "reconstruction 10bps/side is conservative vs this demo but "
                "realistic for production accounts"
            ),
        },
        "slippage_direct_measurement": (
            "NOT MEASURABLE from artifacts (request price not "
            "persisted); deviation cap 10 points active"
        ),
        "min_lot_friction": {
            "bot_fills_all_at_min_lot_0.01": True,
            "implication": (
                "at $5K equity min-lot flooring dominates sizing; intended "
                "|w|*equity often below min-lot notional -> realized weights "
                "differ from target weights"
            ),
        },
        "attribution": {
            "bot_realized_closed_trades_usd": -3.67,
            "manual_realized_closed_trades_usd": -242.65,
            "manual_unrealized_at_export": 353.55,
            "verdict": (
                "$5K campaign P&L NOT attributable to R4; foreign positions "
                "dominate the equity path"
            ),
        },
        "execution_anomalies": [
            "bridge outage 15:13:51Z->00:20Z+ with loop blind and unaudited silent SKIPs",
            "equity_after=0 read failure immediately after fills",
            "deployment drift vs git HEAD (P0-4)",
            "duplicate-alert amplification up to 1:506",
        ],
        "research_vs_live_divergences": [
            "regime universe: research 15 symbols vs live 31 allowed keys vs monitor 6",
            "cadence: manifest weekly vs operational hourly/daily rotation",
            "signal universe includes JPY crosses never tradeable under min-lot rules",
        ],
    }
    jdump(comp, "live_vs_paper_comparison.json")


def phase11_survival_synthesis() -> None:
    surv = {
        "existing_artifacts_reviewed": [
            "docs/production/LONG_DURATION_SURVIVAL_REPORT.md (Verdict: PASS - resources bounded)",
            "docs/production/CHAOS_TESTING.md (unauthorized trading/duplicates/state corruption)",
            "docs/production/DISASTER_RECOVERY.md (broker-authoritative state classification)",
            "git history: clock reliability, restart-recovery chaos tests, bounded retention, supervisor",
        ],
        "claim_vs_deployment_gap": {
            "claim": "HEAD passes endurance + chaos + DR suites; 44 freeze tests pass",
            "deployment_reality": (
                "process that ran the live campaign predates HEAD (no "
                "startup fingerprint logs, missing runtime_state.json/"
                "daily_baseline.json, unknown exit comments in broker "
                "history); those guarantees were NOT active"
            ),
            "severity": "P0-4 in PRELIMINARY_SAFETY_TRIAGE",
        },
        "observed_session_stress_results": {
            "bridge_disconnect_9h": (
                "loop cycled blind hourly with silent SKIPs; "
                "DisconnectRecovery never engaged (not in deployed "
                "build); positions unprotected throughout"
            ),
            "midnight_crossing": (
                "Equity $0.00 reads around midnight UTC create the "
                "daily-baseline poisoning hazard (P1-2)"
            ),
            "flatten_under_contamination": (
                "concurrency gate blocked bot rotation while "
                "foreign magic=0 positions occupied slots"
            ),
        },
        "unmitigated_single_points_of_failure": [
            "single mt5linux bridge host:port (127.0.0.1:8001), no failover, no acting watchdog",
            "single terminal/account dependency",
            "monitor alert-only; Telegram disabled during session",
        ],
        "months_scale_verdict": (
            "UNPROVEN IN DEPLOYMENT: platform tests PASS at HEAD but no "
            "evidence a long-lived deployment ran a HEAD-matching build "
            "with per-cycle fingerprints; observed 12.5h session contained "
            "an outage defeating survival assumptions"
        ),
        "conditions_for_months_scale_operation": [
            "deployed build pinned to audited commit with per-cycle fingerprint proof",
            "bridge failover or watchdog auto-flatten with retry",
            "external escalation channel proven live",
            "absolute audit paths; audited SKIP events",
        ],
    }
    jdump(surv, "long_duration_survival.json")


MIN_LOT_NOTIONAL = {
    "AUDUSD": 716,
    "AUDCHF": 574,
    "AUDCAD": 990,
    "AUDNZD": 1199,
    "NZDUSD": 597,
    "NZDCHF": 479,
    "NZDCAD": 826,
    "GBPUSD": 1363,
    "GBPCHF": 1094,
    "EURUSD": 1167,
    "EURCHF": 937,
    "USDCHF": 803,
    "USDCAD": 1384,
    "CADCHF": 580,
    "EURGBP": 856,
    "BTCUSD": 792,
}


def phase12_capital_scaling() -> None:
    tiers = [5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]
    typical_w, max_w = 0.05, 0.20
    rows = []
    for eq in tiers:
        pos_cap = 0.30 * eq
        rows.append(
            {
                "tier_usd": eq,
                "max_position_notional_30pct": round(pos_cap),
                "symbols_minlot_fits_poscap": f"{sum(1 for v in MIN_LOT_NOTIONAL.values() if v <= pos_cap)}/16",
                "symbols_typical_target_ge_minlot": f"{sum(1 for v in MIN_LOT_NOTIONAL.values() if v <= typical_w * eq)}/16",
                "symbols_untradeable_even_at_max_clip": f"{sum(1 for v in MIN_LOT_NOTIONAL.values() if v > max_w * eq)}/16",
                "gross_exposure_cap_8pos": round(8 * pos_cap),
                "expected_maxdd_relative": "-12.3% control backtest; scales with capital",
                "liquidity_note": "FX crosses absorb these sizes at negligible impact; BTC fine < $10M gross",
                "broker_limits_note": "max_volume 1.0 lot binds ~$130K+ per single FX order; multi-order possible",
            }
        )
    jdump(
        {
            "method": (
                "per-tier constraint mapping: config min-lot notionals, 30% position cap, "
                "|w| clip 0.20, top-8; no linear performance extrapolation"
            ),
            "rows": rows,
            "evidence_gated_verdicts": {
                "5000": "CONDITIONAL - only tier with live evidence; evidence contaminated (P0-3), safety gaps open (P0-1)",
                "10000": "NOT JUSTIFIED YET - requires clean post-P0-fix qualification + preregistered variant acceptance",
                "25000": "NOT JUSTIFIED YET",
                "50000": "NOT JUSTIFIED YET - GBPUSD/EURUSD/AUDNZD approach flooring at typical |w|",
                "100000": "NOT JUSTIFIED YET - single-order lot caps begin to bind; multi-fill unproven",
                "250000": "NOT JUSTIFIED YET",
                "500000": "NOT JUSTIFIED YET - RiskPolicy 25% concentration conflicts with 30% position design; redesign needed",
                "1000000": "NOT JUSTIFIED YET - strategy capacity unproven; needs execution-capacity study + broker agreements",
            },
            "promotion_requires_new_evidence": [
                "clean reconciled qualification window at current tier",
                "preregistered OOS-validated risk improvements deployed",
                "execution-quality telemetry meeting config limits on live fills",
                "independent catastrophic protection layer active and tested",
            ],
        },
        "capital_scaling.json",
    )


def block_bootstrap_ann(r: pd.Series, n_boot=2000, block=20, seed=11):
    x = r.dropna().to_numpy()
    rng = np.random.default_rng(seed)
    nb = max(len(x) // block, 1)
    out = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, len(x) - block, size=nb)
        out[b] = (
            np.concatenate([x[s : s + block] for s in starts])[: len(x)].mean() * 252
        )
    return out


def phase13_profitability() -> None:
    curve = pd.read_csv(OUT / "curve_control.csv", index_col=0, parse_dates=True)[
        "port_net"
    ]
    boot = block_bootstrap_ann(curve)
    vol = float(curve.std() * np.sqrt(252))
    monthly = curve.groupby(curve.index.to_period("M")).sum()
    scen = {}
    for name, q in [("conservative", 10), ("baseline", 50), ("optimistic", 90)]:
        ann = float(np.percentile(boot, q))
        t2d = log(2) / log(1 + ann) if ann > 0 else float("inf")
        z = log(0.8) / vol
        p_hit_dd = 0.5 * (1 + erf(z / sqrt(2)))
        scen[name] = {
            "ann_return_bootstrap_pctile": {
                "conservative": "P10",
                "baseline": "P50",
                "optimistic": "P90",
            }[name],
            "ann_return": ann,
            "ann_vol": vol,
            "sharpe_ann": ann / vol if vol > 0 else None,
            "prob_losing_month_empirical": float((monthly < 0).mean()),
            "time_to_double_years_compounded": t2d,
            "prob_hit_20pct_dd_within_1y_normal_approx": p_hit_dd,
        }
    pc = pd.read_csv(OUT / "portfolio_curve_daily.csv", index_col=0, parse_dates=True)
    drag_ann = float(
        (pc["ret_gross_weighted"].mean() - pc["ret_net_weighted"].mean()) * 252
    )
    jdump(
        {
            "basis": (
                "block-bootstrap (20d blocks, 2000 draws) of control daily net returns "
                "2021..2026-08 at 10bps/side costs; STATISTICAL SCENARIO, NOT A GUARANTEE"
            ),
            "scenarios": scen,
            "cost_drag_gross_minus_net_annualized": drag_ann,
            "compounding_note": (
                "sizing capped by max_equity=$5100 during qualification; "
                "compounding intentionally disabled until capital promotion"
            ),
            "max_drawdown_control_backtest": -0.123,
            "campaign_daily_loss_limit_usd": 250.0,
            "prob_daily_loss_beyond_limit_normal_approx": float(
                1 - 0.5 * (1 + erf((250.0 / 5010.94) / (vol / sqrt(252)) / sqrt(2)))
            ),
        },
        "profitability_scenarios.json",
    )


if __name__ == "__main__":
    phase10_live_comparison()
    phase11_survival_synthesis()
    phase12_capital_scaling()
    phase13_profitability()
