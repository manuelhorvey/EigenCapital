"""R4-B1 Pairs Runner — the preregistered mean-reversion/stat-arb experiment.

Frozen contract: docs/research/R4_MEAN_REVERSION.md (R4-A contract items 1–15
+ pre-execution addendum). This runner:

- runs the TWO preregistered pairs (AUDUSDm/NZDUSDm, EURUSDm/GBPUSDm) through
  `run_pair` — the frozen pipeline, no threshold search anywhere;
- applies the frozen family verdict:
    F-A  pooled OOS per-trade GROSS P&L, sign-flip permutation p < 0.05
    F-B  pooled OOS NET total P&L > 0 (4 × 15 bps per round trip, deducted)
    F-C  Pearson correlation with the frozen-R4 replica daily path < 0.7
  CANDIDATE requires the sample gate (≥ 20 round-trips/pair) on ≥ 1 pair
  AND all three arms; any failed arm → REJECTED; missing evidence →
  INCONCLUSIVE (never PASS — no VALIDATED verdict exists in EigenCapital);
- emits JSON + MD artifacts plus per-pair trade CSVs.

This is a RESEARCH experiment on a research-only family. A REJECTED verdict
says nothing about the frozen R4 production strategy; the promotion question
is incremental portfolio utility, never "can this match R4?".
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

# Preregistered universe (contract item 1) — exactly these two pairs.
PAIRS: List[Tuple[str, str]] = [("AUDUSDm", "NZDUSDm"), ("EURUSDm", "GBPUSDm")]
SAMPLE_GATE_MIN_TRADES = 20  # contract item 7
OOS_EXIT_INDEX = WF_TRAIN_BARS + WF_PURGE_BARS + WF_EMBARGO_BARS  # frozen OOS split
FC_MAX_CORRELATION = 0.7  # contract item 11, F-C
FC_MIN_OVERLAP_DAYS = 100  # below this, F-C is missing evidence
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
    """LOG close prices for the four preregistered symbols (contract item 2)."""
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
    """Frozen-R4 replica daily path (pre-execution addendum, F-C comparator)."""
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
        la, lb = log_prices[sym_a], log_prices[sym_b]
        result = run_pair(la, lb, (sym_a, sym_b))
        pair_results[label] = result
        pair_common[label] = _pair_common_index(la, lb)

    # ── Sample gate (contract item 7) + OOS partition (addendum) ────────────
    per_pair: List[Dict[str, Any]] = []
    pooled_oos_gross: List[float] = []
    pooled_oos_net: float = 0.0
    pooled_oos_n: int = 0
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
        pooled_oos_gross.extend(float(t["gross_pnl"]) for t in oos_trades)
        pooled_oos_net += sum(float(t["net_pnl"]) for t in oos_trades)
        pooled_oos_n += len(oos_trades)

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
                "total_pnl_net": res.total_pnl,
                "hit_rate": res.hit_rate,
                "n_cancelled_entries": res.n_cancelled_entries,
                "wf_total_windows": wf.total_windows,
                "wf_mean_oos_sharpe": wf.mean_oos_sharpe,
                "wf_pct_profitable_windows": wf.pct_profitable_windows,
                "wf_reason": wf_reason,
                "oos_net_pnl": sum(float(t["net_pnl"]) for t in oos_trades),
                "oos_gross_mean_per_trade": (
                    float(np.mean([float(t["gross_pnl"]) for t in oos_trades])) if oos_trades else None
                ),
            }
        )
        _write_pair_csv(label, res)

    # ── F-A: sign-flip permutation on pooled OOS gross per-trade P&L ────────
    fa_perm = None
    fa_p: Any = None
    if len(pooled_oos_gross) >= 2:
        fa_perm = permutation_test(pooled_oos_gross, PERMUTATION_N, PERMUTATION_SEED)
        fa_p = fa_perm.p_value
    fa_pass = bool(fa_perm is not None and fa_perm.n_permutations > 0 and fa_p is not None and fa_p < 0.05)
    fa_missing = fa_perm is None or fa_perm.n_permutations == 0

    # ── F-B: pooled OOS net P&L after full costs ────────────────────────────
    fb_missing = pooled_oos_n == 0
    fb_pass = (not fb_missing) and pooled_oos_net > 0.0

    # ── F-C: correlation with the frozen-R4 replica daily path ──────────────
    family_daily = pd.concat(daily_frames, axis=1).mean(axis=1).dropna()
    joined = pd.concat([family_daily.rename("mr"), r4_daily.rename("r4")], axis=1).dropna()
    fc_missing = len(joined) < FC_MIN_OVERLAP_DAYS
    fc_corr: Any = None
    fc_pass = False
    if not fc_missing:
        fc_corr = float(joined["mr"].corr(joined["r4"]))
        fc_pass = fc_corr is not None and fc_corr < FC_MAX_CORRELATION

    # ── Family verdict (frozen logic, explicit) ─────────────────────────────
    sample_gate_ok = any(p["sample_gate_pass"] for p in per_pair)
    if fa_missing or fb_missing or fc_missing or not sample_gate_ok:
        outcome = "INCONCLUSIVE"
        missing = []
        if not sample_gate_ok:
            missing.append("sample gate (≥ 20 round-trips) failed on every pair")
        if fa_missing:
            missing.append("F-A: insufficient OOS trades for the permutation test")
        if fb_missing:
            missing.append("F-B: no OOS trades")
        if fc_missing:
            missing.append(f"F-C: overlap {len(joined)} days < {FC_MIN_OVERLAP_DAYS}")
        statement = (
            "the family verdict is INCONCLUSIVE — "
            + "; ".join(missing)
            + ". Missing evidence is never promoted to a pass."
        )
    elif fa_pass and fb_pass and fc_pass:
        outcome = "CANDIDATE"
        statement = (
            f"the two-pair family passed all three preregistered falsification "
            f"arms on this data (F-A p={fa_p:.4f}, F-B OOS net {pooled_oos_net:.4f}, "
            f"F-C rho={fc_corr:.3f}) — CANDIDATE status within research only; "
            f"production promotion requires the frozen stage-boundary process"
        )
    else:
        failed = [name for name, ok in (("F-A", fa_pass), ("F-B", fb_pass), ("F-C", fc_pass)) if not ok]
        outcome = "REJECTED"
        statement = (
            "the two-pair family FAILED the preregistered falsification arm(s) "
            + ", ".join(failed)
            + " on this data — REJECTED within research only; this says nothing "
            "about the frozen R4 production strategy"
        )

    meta: Dict[str, Any] = {
        "experiment": "R4-B1 mean-reversion / stat-arb preregistered pairs",
        "contract": "docs/research/R4_MEAN_REVERSION.md",
        "timestamp_utc": timestamp,
        "universe_version": "r4_local_v1",
        "pairs": [f"{a}/{b}" for a, b in PAIRS],
        "oos_exit_index": OOS_EXIT_INDEX,
        "cost_per_round_trip": 4 * 0.0015,
        "permutation": {"n": PERMUTATION_N, "seed": PERMUTATION_SEED},
        "verdict": {"outcome": outcome, "statement": statement},
        "f_a": {
            "statistic": "sign-flip permutation on pooled OOS per-trade gross P&L",
            "p_value": fa_p,
            "observed_sharpe_of_trades": (fa_perm.observed_sharpe if fa_perm else None),
            "n_oos_trades": pooled_oos_n,
            "missing": fa_missing,
        },
        "f_b": {
            "statistic": "pooled OOS net total P&L after 4×15 bps per round trip",
            "value": pooled_oos_net,
            "n_oos_trades": pooled_oos_n,
            "missing": fb_missing,
        },
        "f_c": {
            "statistic": "Pearson correlation vs frozen-R4 replica daily path",
            "value": fc_corr,
            "overlap_days": int(len(joined)),
            "missing": fc_missing,
        },
        "pair_diagnostics": per_pair,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "r4_b1_pairs_report.json", "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    (REPORTS / "r4_b1_report.md").write_text(_render(meta))
    print(f"[R4-B1] verdict: {outcome}")
    print(f"[R4-B1] {statement}")
    print(f"[R4-B1] artifacts in {REPORTS}/")


def _write_pair_csv(label: str, res: PairResult) -> None:
    safe = label.replace("/", "_")
    path = REPORTS / f"r4_b1_{safe}_trades.csv"
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
        "# R4-B1 — Mean Reversion / Stat-Arb Pairs (OBSERVED report)",
        "",
        f"**Experiment:** {meta['experiment']}  ",
        f"**Contract:** `{meta['contract']}` (frozen before code; pre-execution addendum)  ",
        f"**Run:** {meta['timestamp_utc']} · deterministic (seeded permutation only)  ",
        f"**Universe:** {meta['universe_version']} — pairs: {', '.join(meta['pairs'])}  ",
        f"**OOS split:** exit bar index ≥ {meta['oos_exit_index']} (frozen R3 WF geometry)  ",
        f"**Costs:** {meta['cost_per_round_trip'] * 1e4:.0f} bps per round trip (4 legs × 15 bps)",
        "",
        "> **What this is:** a research-only mean-reversion/stat-arb family",
        "> evaluated against its preregistered falsification arms.",
        "> **What this is NOT:** a statement about the frozen R4 production",
        "> strategy, and not a promotion decision.",
        "",
        f"## Verdict: **{v['outcome']}**",
        "",
        f"> {v['statement']}.",
        "",
        "## Falsification arms",
        "",
        f"- **F-A** (OOS gross per-trade edge, sign-flip permutation): p = "
        f"{meta['f_a']['p_value']} over {meta['f_a']['n_oos_trades']} OOS trades",
        f"- **F-B** (OOS net P&L after full costs): {meta['f_b']['value']:.4f}",
        f"- **F-C** (correlation with frozen-R4 replica < 0.7): "
        f"rho = {meta['f_c']['value']} over {meta['f_c']['overlap_days']} overlap days",
        "",
        "## Per-pair diagnostics",
        "",
        "| Pair | bars | est. dates | active | trades (IS/OOS) | gate≥20 | net P&L | hit rate | cancelled | WF windows | WF mean OOS Sharpe |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in meta["pair_diagnostics"]:
        lines.append(
            f"| {p['pair']} | {p['n_common_bars']} | {p['n_estimation_dates']} | "
            f"{p['n_regime_active']} | {p['n_round_trips_is']}/{p['n_round_trips_oos']} | "
            f"{'PASS' if p['sample_gate_pass'] else 'FAIL'} | {p['total_pnl_net']:.4f} | "
            f"{p['hit_rate']:.3f} | {p['n_cancelled_entries']} | "
            f"{p['wf_total_windows']}{' (' + p['wf_reason'] + ')' if p['wf_reason'] else ''} | "
            f"{p['wf_mean_oos_sharpe']:.3f} |"
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
        "- REJECTED / CANDIDATE / INCONCLUSIVE are **research-family verdicts**",
        "  about this replica pipeline on this data — never verdicts on the",
        "  frozen R4 production strategy.",
        "- One preregistered trial slot is consumed by this family verdict;",
        "  threshold or universe changes require a NEW preregistration.",
        "- INCONCLUSIVE is never read as a pass; no VALIDATED verdict exists.",
        "- Promotion question is incremental portfolio utility (F-C), not",
        "  standalone return parity with R4.",
        "",
        f"*Artifacts: r4_b1_pairs_report.json + per-pair trade CSVs in {REPORTS}/.*",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
