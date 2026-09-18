"""R4-B2 Pairs Runner — preregistered 8-pair mean-reversion family.

Frozen contract: docs/research/R4_MEAN_REVERSION.md § R4-B2 preregistration
(frozen BEFORE any B2 code or data access). This runner:

- runs the EIGHT preregistered pairs through `run_pair` — the UNCHANGED frozen
  B1 pipeline (250-bar window, 21-bar step, ADF ∧ cointegration ∧ half-life
  gates, z ±2.0/±0.5, 60-bar z window, one-bar lag, 4×15 bps round trip);
- applies the ONE preregistered Holm family over the 8 per-pair sign-flip
  permutation p-values (F-A), with F-B and F-C recomputed as in B1;
- enforces the pre-committed PARKING RULE: < 20 total trades across the
  family → family parked on daily bars, no further attempts on this data
  class (registered in the ledger before execution);
- emits JSON + MD artifacts plus per-pair trade CSVs.

Research-only family. A verdict here says nothing about the frozen R4
production strategy; the promotion question is incremental portfolio utility.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eigencapital.analytics.validation.bootstrap import permutation_test
from eigencapital.analytics.validation.multiple_testing import multiple_testing_correction
from eigencapital.analytics.validation.walk_forward import WalkForwardResult, purged_walk_forward
from eigencapital.research.mean_reversion.pipeline import PairResult, run_pair
from eigencapital.research.parameter_stability.evaluate import (
    daily_portfolio_path,
    equity_curve_from_returns,
)
from eigencapital.research.parameter_stability.grid import (
    WF_EMBARGO_BARS,
    WF_PURGE_BARS,
    WF_TEST_BARS,
    WF_TRAIN_BARS,
)

REPORTS = Path("reports/r4_mean_reversion")

# Preregistered 8-pair universe (B2 preregistration table) — economic rationale
# declared in the ledger BEFORE any statistic was computed. NOT pair-mined.
PAIRS: List[Tuple[str, str]] = [
    ("AUDUSDm", "NZDUSDm"),  # carried over from B1 (commodity-currency bloc)
    ("EURUSDm", "GBPUSDm"),  # carried over from B1 (European majors)
    ("EURUSDm", "USDCHFm"),  # product = EURCHF; SNB/Eurozone policy linkage
    ("USDCADm", "USOILm"),  # petro-currency (CAD tracks crude)
    ("XAUUSDm", "XAGUSDm"),  # monetary metals, shared macro driver
    ("US30m", "US500m"),  # same-market index pair, shared equity beta
    ("USTECm", "US500m"),  # US equity vs tech-tilted index
    ("BTCUSDm", "ETHUSDm"),  # shared crypto beta
]
SAMPLE_GATE_MIN_TRADES = 20  # unchanged from B1
PARKING_RULE_MIN_TOTAL_TRADES = 20  # pre-committed B2 parking rule
OOS_EXIT_INDEX = WF_TRAIN_BARS + WF_PURGE_BARS + WF_EMBARGO_BARS  # frozen OOS split
FC_MAX_CORRELATION = 0.7
FC_MIN_OVERLAP_DAYS = 100
PERMUTATION_N = 1000
PERMUTATION_SEED = 42


def _load_exporter() -> Any:
    path = Path(__file__).resolve().parent / "export_r4_trade_stream.py"
    spec = importlib.util.spec_from_file_location("r4_exporter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r4_exporter"] = module
    spec.loader.exec_module(module)
    return module


def _load_log_prices() -> Dict[str, pd.Series]:
    """LOG close prices for every preregistered B2 symbol."""
    log_prices: Dict[str, pd.Series] = {}
    for sym in sorted({s for pair in PAIRS for s in pair}):
        path = Path("data/mt5") / f"{sym}_D1.csv"
        if not path.is_file():
            raise SystemExit(f"preregistered symbol missing from data: {sym}")
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time").sort_index()
        close = df["close"]
        if (close <= 0).any() or not np.isfinite(close).all():
            raise SystemExit(f"{sym}: non-positive or non-finite closes")
        log_prices[sym] = np.log(close.astype(float))
    return log_prices


def _pair_common_index(la: pd.Series, lb: pd.Series) -> pd.DatetimeIndex:
    return la.index.intersection(lb.index)


def _wf_aggregate(daily: pd.Series) -> Tuple[WalkForwardResult, str]:
    """Frozen R3 geometry; windows-that-cannot-fit reported with reason."""
    equity = equity_curve_from_returns(daily)
    n = len(equity)
    if n < WF_TRAIN_BARS + WF_PURGE_BARS + WF_TEST_BARS:
        return (
            WalkForwardResult(
                total_windows=0,
                purge_bars=WF_PURGE_BARS,
                embargo_bars=WF_EMBARGO_BARS,
            ),
            f"path of {n} bars < train+purge+test ({WF_TRAIN_BARS + WF_PURGE_BARS + WF_TEST_BARS}) — cannot fit",
        )
    wf = purged_walk_forward(
        equity_curve=equity,
        train_bars=WF_TRAIN_BARS,
        test_bars=WF_TEST_BARS,
        purge_bars=WF_PURGE_BARS,
        embargo_bars=WF_EMBARGO_BARS,
        anchored=True,
    )
    return wf, ""


def _frozen_r4_daily(exporter: Any) -> pd.Series:
    """Frozen-R4 replica daily path (F-C comparator)."""
    base = exporter.load_config_params()
    data = exporter.load_bars()
    weights = exporter.compute_r4_signal(data, dict(base))
    return daily_portfolio_path(data, weights, float(base["cost_one_way"]))


def main() -> None:
    timestamp = datetime.now(UTC).isoformat()
    exporter = _load_exporter()
    log_prices = _load_log_prices()
    r4_daily = _frozen_r4_daily(exporter)

    pair_results: Dict[str, PairResult] = {}
    pair_common: Dict[str, pd.DatetimeIndex] = {}
    for sym_a, sym_b in PAIRS:
        label = f"{sym_a}/{sym_b}"
        result = run_pair(log_prices[sym_a], log_prices[sym_b], (sym_a, sym_b))
        pair_results[label] = result
        pair_common[label] = _pair_common_index(log_prices[sym_a], log_prices[sym_b])

    # ── Per-pair diagnostics + OOS partition (identical to B1) ──────────────
    per_pair: List[Dict[str, Any]] = []
    pair_p: Dict[str, Any] = {}  # raw per-pair sign-flip p-values
    pooled_oos_net: float = 0.0
    total_trades = 0
    daily_frames: List[pd.Series] = []

    for label, res in pair_results.items():
        common = pair_common[label]
        pos_of = {d: i for i, d in enumerate(common)}
        oos_trades, is_trades = [], []
        for t in res.round_trips:
            exit_pos = pos_of.get(pd.Timestamp(t["exit_date"]))
            if exit_pos is not None and exit_pos >= OOS_EXIT_INDEX:
                oos_trades.append(t)
            else:
                is_trades.append(t)
        pooled_oos_net += sum(float(t["net_pnl"]) for t in oos_trades)
        total_trades += len(res.round_trips)

        oos_gross = [float(t["gross_pnl"]) for t in oos_trades]
        perm = None
        p_raw: Any = None
        if len(oos_gross) >= 2:
            perm = permutation_test(oos_gross, PERMUTATION_N, PERMUTATION_SEED)
            p_raw = perm.p_value
        pair_p[label] = p_raw

        wf, wf_reason = _wf_aggregate(res.daily_returns)
        daily_frames.append(res.daily_returns.rename(label))
        per_pair.append(
            {
                "pair": label,
                "n_common_bars": len(common),
                "n_estimation_dates": res.n_estimation_dates,
                "n_regime_active": res.n_regime_active,
                "gate_failures": dict(res.n_gate_failures),
                "n_round_trips_total": len(res.round_trips),
                "n_round_trips_is": len(is_trades),
                "n_round_trips_oos": len(oos_trades),
                "sample_gate_pass": len(res.round_trips) >= SAMPLE_GATE_MIN_TRADES,
                "sign_flip_p_raw": p_raw,
                "total_pnl_net": res.total_pnl,
                "hit_rate": res.hit_rate,
                "n_cancelled_entries": res.n_cancelled_entries,
                "wf_total_windows": wf.total_windows,
                "wf_mean_oos_sharpe": wf.mean_oos_sharpe,
                "wf_pct_profitable_windows": wf.pct_profitable_windows,
                "wf_reason": wf_reason,
                "oos_net_pnl": sum(float(t["net_pnl"]) for t in oos_trades),
            }
        )
        _write_pair_csv(label, res)

    # ── ONE preregistered Holm family over the 8 per-pair p-values ──────────
    tested = {k: v for k, v in pair_p.items() if v is not None}
    holm: Dict[str, Any] = {}
    if len(tested) >= 2:
        labels = list(tested)
        mtc = multiple_testing_correction(
            [float(tested[k]) for k in labels],
            method="holm",
            alpha=0.05,
            family_definition="R4-B2: 8-pair mean-reversion family, per-pair sign-flip permutation p-values",
        )
        corrected = list(mtc.adjusted_p_values)
        holm = {
            "method": "holm",
            "family_definition": "R4-B2: 8-pair mean-reversion family, per-pair sign-flip permutation p-values",
            "n_tests": len(labels),
            "per_pair": {k: {"raw": tested[k], "holm_adjusted": corrected[i]} for i, k in enumerate(labels)},
            "any_significant_after_holm": any(p < 0.05 for p in corrected),
        }
    else:
        holm = {
            "method": "holm",
            "family_definition": "R4-B2: 8-pair mean-reversion family, per-pair sign-flip permutation p-values",
            "n_tests": len(tested),
            "per_pair": {},
            "any_significant_after_holm": False,
            "note": f"only {len(tested)} pair(s) had ≥2 OOS trades — Holm family not applicable; missing evidence stays missing",
        }

    # ── Pre-committed parking rule (registered BEFORE execution) ────────────
    parking_rule_fired = total_trades < PARKING_RULE_MIN_TOTAL_TRADES

    # ── F-B: pooled OOS net P&L after full costs ────────────────────────────
    n_oos = sum(p["n_round_trips_oos"] for p in per_pair)
    fb_missing = n_oos == 0
    fb_pass = (not fb_missing) and pooled_oos_net > 0.0

    # ── F-C: correlation with the frozen-R4 replica daily path (diagnostic) ─
    family_daily = pd.concat(daily_frames, axis=1).mean(axis=1).dropna()
    joined = pd.concat([family_daily.rename("mr"), r4_daily.rename("r4")], axis=1).dropna()
    fc_missing = len(joined) < FC_MIN_OVERLAP_DAYS
    fc_corr: Any = None
    fc_pass = False
    if not fc_missing:
        fc_corr = float(joined["mr"].corr(joined["r4"]))
        fc_pass = fc_corr is not None and fc_corr < FC_MAX_CORRELATION

    # ── Family verdict (frozen logic + parking rule) ────────────────────────
    sample_gate_ok = any(p["sample_gate_pass"] for p in per_pair)
    fa_missing = len(tested) < len(PAIRS)
    if parking_rule_fired:
        outcome = "PARKED"
        statement = (
            f"pre-committed parking rule FIRED: {total_trades} total trades across "
            f"the 8-pair family < {PARKING_RULE_MIN_TOTAL_TRADES}. The mean-reversion "
            "family is PARKED on daily bars — no gate recalibration, no window changes, "
            "no universe expansion beyond this set, no re-attempt on this data class. "
            "Reopening requires a material data upgrade (intraday or order-flow data). "
            "The hypothesis remains unresolved-not-falsified on this data class."
        )
    elif fa_missing or fb_missing or fc_missing or not sample_gate_ok:
        outcome = "INCONCLUSIVE"
        missing = []
        if not sample_gate_ok:
            missing.append("sample gate (≥ 20 round-trips) failed on every pair")
        if fa_missing:
            missing.append("F-A: some pairs lack ≥2 OOS trades for the permutation test")
        if fb_missing:
            missing.append("F-B: no OOS trades")
        if fc_missing:
            missing.append(f"F-C: overlap {len(joined)} days < {FC_MIN_OVERLAP_DAYS}")
        statement = (
            "the family verdict is INCONCLUSIVE — "
            + "; ".join(missing)
            + ". Missing evidence is never promoted to a pass."
        )
    elif holm.get("any_significant_after_holm") and fb_pass and fc_pass:
        best = min(holm["per_pair"].items(), key=lambda kv: kv[1]["holm_adjusted"])
        outcome = "CANDIDATE"
        statement = (
            f"the 8-pair family passed the preregistered arms on this data "
            f"(best Holm-adjusted pair: {best[0]} p={best[1]['holm_adjusted']:.4f}; "
            f"F-B OOS net {pooled_oos_net:.4f}; F-C rho={fc_corr:.3f}) — CANDIDATE "
            f"status within research only; production promotion requires the frozen "
            f"stage-boundary process"
        )
    else:
        failed = [
            name
            for name, ok in (("F-A(Holm)", holm.get("any_significant_after_holm")), ("F-B", fb_pass), ("F-C", fc_pass))
            if not ok
        ]
        outcome = "REJECTED"
        statement = (
            "the 8-pair family FAILED the preregistered falsification arm(s) "
            + ", ".join(failed)
            + " on this data — REJECTED within research only; this says nothing "
            "about the frozen R4 production strategy"
        )

    meta: Dict[str, Any] = {
        "experiment": "R4-B2 mean-reversion / stat-arb preregistered 8-pair family",
        "contract": "docs/research/R4_MEAN_REVERSION.md (R4-B2 preregistration, frozen before code/data access)",
        "timestamp_utc": timestamp,
        "universe_version": "r4_local_v1_b2",
        "pairs": [f"{a}/{b}" for a, b in PAIRS],
        "oos_exit_index": OOS_EXIT_INDEX,
        "cost_per_round_trip": 4 * 0.0015,
        "permutation": {"n": PERMUTATION_N, "seed": PERMUTATION_SEED},
        "parking_rule": {
            "min_total_trades": PARKING_RULE_MIN_TOTAL_TRADES,
            "total_trades_observed": total_trades,
            "fired": parking_rule_fired,
        },
        "holm_family": holm,
        "verdict": {"outcome": outcome, "statement": statement},
        "f_b": {
            "statistic": "pooled OOS net P&L after 4×15 bps per round trip",
            "value": pooled_oos_net,
            "n_oos_trades": n_oos,
            "missing": fb_missing,
        },
        "f_c": {
            "statistic": "Pearson correlation vs frozen-R4 replica daily path (diagnostic only)",
            "value": fc_corr,
            "overlap_days": int(len(joined)),
            "missing": fc_missing,
        },
        "pair_diagnostics": per_pair,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "r4_b2_pairs_report.json", "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    (REPORTS / "r4_b2_report.md").write_text(_render(meta))
    print(f"[R4-B2] verdict: {outcome}")
    print(f"[R4-B2] {statement}")
    print(f"[R4-B2] artifacts in {REPORTS}/")


def _write_pair_csv(label: str, res: PairResult) -> None:
    safe = label.replace("/", "_")
    path = REPORTS / f"r4_b2_{safe}_trades.csv"
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows = ["direction,entry_date,exit_date,entry_z,exit_z,beta,alpha,gross_pnl,cost,net_pnl,close_reason"]
    for t in res.round_trips:
        rows.append(
            ",".join(
                str(t[k].date() if isinstance(t[k], pd.Timestamp) else t[k])
                for k in (
                    "direction",
                    "entry_date",
                    "exit_date",
                    "entry_z",
                    "exit_z",
                    "beta",
                    "alpha",
                    "gross_pnl",
                    "cost",
                    "net_pnl",
                    "close_reason",
                )
            )
        )
    path.write_text("\n".join(rows) + "\n")


def _render(meta: Dict[str, Any]) -> str:
    v = meta["verdict"]
    lines: List[str] = [
        "# R4-B2 — Mean Reversion / Stat-Arb 8-Pair Family (OBSERVED report)",
        "",
        f"**Experiment:** {meta['experiment']}  ",
        f"**Contract:** `{meta['contract']}` — preregistration frozen BEFORE code and data access  ",
        f"**Run:** {meta['timestamp_utc']} · deterministic (seed {meta['permutation']['seed']}, n={meta['permutation']['n']})  ",
        f"**Universe:** {meta['universe_version']} — 8 pairs, economic rationale declared ex ante (see ledger)  ",
        f"**OOS split:** exit bar index ≥ {meta['oos_exit_index']} (frozen R3 WF geometry)  ",
        f"**Costs:** {meta['cost_per_round_trip'] * 1e4:.0f} bps per round trip (4 legs × 15 bps)",
        "",
        "> **What this is:** a research-only mean-reversion/stat-arb family",
        "> evaluated against its preregistered falsification arms and the",
        "> pre-committed parking rule.",
        "> **What this is NOT:** a statement about the frozen R4 production",
        "> strategy, and not a promotion decision.",
        "",
        f"## Verdict: **{v['outcome']}**",
        "",
        f"> {v['statement']}.",
        "",
        "## Pre-committed parking rule",
        "",
        f"- Threshold: < {meta['parking_rule']['min_total_trades']} total trades across the family → PARKED.",
        f"- Observed: **{meta['parking_rule']['total_trades_observed']} total trades** → "
        + ("**RULE FIRED.**" if meta["parking_rule"]["fired"] else "rule not triggered.")
        + "",
        "",
        "## Holm family (ONE preregistered family over the 8 pairs)",
        "",
        f"- {meta['holm_family']['family_definition']}",
        f"- n_tests = {meta['holm_family']['n_tests']}; any pair significant after Holm: "
        f"**{meta['holm_family']['any_significant_after_holm']}**"
        + (f" — {meta['holm_family'].get('note')}" if meta["holm_family"].get("note") else "")
        + "",
        "",
    ]
    per_pair_holm = meta["holm_family"].get("per_pair") or {}
    if per_pair_holm:
        lines += ["| Pair | raw p | Holm-adjusted p |", "|---|---|---|"]
        for k, pv in per_pair_holm.items():
            lines.append(f"| {k} | {pv['raw']:.4f} | {pv['holm_adjusted']:.4f} |")
        lines.append("")
    lines += [
        "## Falsification arms",
        "",
        f"- **F-B** (pooled OOS net P&L after full costs): {meta['f_b']['value']:.4f} over {meta['f_b']['n_oos_trades']} OOS trades",
        f"- **F-C** (correlation with frozen-R4 replica < 0.7, diagnostic): rho = {meta['f_c']['value']} over {meta['f_c']['overlap_days']} overlap days",
        "",
        "## Per-pair diagnostics",
        "",
        "| Pair | bars | est. dates | active | trades (IS/OOS) | gate≥20 | raw p | net P&L | hit rate | cancelled | WF windows |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in meta["pair_diagnostics"]:
        p_str = "n/a" if p["sign_flip_p_raw"] is None else f"{p['sign_flip_p_raw']:.4f}"
        lines.append(
            f"| {p['pair']} | {p['n_common_bars']} | {p['n_estimation_dates']} | "
            f"{p['n_regime_active']} | {p['n_round_trips_is']}/{p['n_round_trips_oos']} | "
            f"{'PASS' if p['sample_gate_pass'] else 'FAIL'} | {p_str} | {p['total_pnl_net']:.4f} | "
            f"{p['hit_rate']:.3f} | {p['n_cancelled_entries']} | "
            f"{p['wf_total_windows']}{' (' + p['wf_reason'] + ')' if p['wf_reason'] else ''} |"
        )
    lines += [
        "",
        "Gate failures by type (across estimation dates):",
        "",
    ]
    for p in meta["pair_diagnostics"]:
        lines.append(f"- {p['pair']}: {p['gate_failures']} (active {p['n_regime_active']}/{p['n_estimation_dates']})")
    lines += [
        "",
        "## Interpretation guards (frozen)",
        "",
        "- PARKED / REJECTED / CANDIDATE / INCONCLUSIVE are **research-family verdicts**",
        "  about this replica pipeline on this data — never verdicts on the",
        "  frozen R4 production strategy.",
        "- One preregistered trial slot (R4-B2) consumed by this family verdict;",
        "  any gate/window/universe change requires a NEW preregistration.",
        "- The parking rule was registered BEFORE execution; it is not a post-hoc",
        "  stopping choice.",
        "- INCONCLUSIVE is never read as a pass; no VALIDATED verdict exists.",
        "- Pair selection was by declared economic rationale, not by scanning",
        "  cointegration statistics (no pair-mining).",
        "",
        f"*Artifacts: r4_b2_pairs_report.json + per-pair trade CSVs in {REPORTS}/.*",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
