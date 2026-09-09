"""R4-S Diagnostics — where does the lost edge go, and is there a stable
risk/edge frontier?

Reads the shadow evidence produced by scripts/r4_shadow_portfolio.py and
computes the diagnostic analyses (research phase, NOT optimization):

  D1. Edge retained by selection size (top-1/2/4/6/8) — where edge collapses.
  D2. Lost-edge attribution — every R4 name excluded by the shadow portfolio
      is charged to one dominant measurable reason (final-state recomputed).
  D3. Risk/edge frontier — R4 vs shadow chain P_1..P_8, gross AND net of the
      project's 10 bps/side cost convention, plus realized outcomes.
  D3b. Comparative evidence table — R4-20 vs Shadow-4..8 across the full
      metric set (signal retained, vol/variance, currency/factor
      concentration, effective bets, gross/net exposure, risk-contribution
      concentration, realized R, drawdown, turnover).
  D3c. Signal/risk efficiency — per-transition Δsignal / Δvariance, showing
      where additional R4 signal becomes inefficient relative to incremental
      modeled risk (decision-time only; not a promotion criterion).
  D4. Realized-outcome evaluation — R4-20 vs Shadow-4..8 on the per-cycle
      size ledger: realized P&L/R, Sharpe, max DD, realized vol, downside
      deviation, worst cycle, tail loss, turnover, costs, ERC.
  D5. Regime interaction — decision days bucketed by vol_now/vol_median.

Outputs:
    printed tables + reports/r4_loop/shadow_diagnostics_summary.json

Usage:
    python scripts/r4_shadow_diagnostics.py [--out-dir reports/r4_loop]
    python scripts/r4_shadow_diagnostics.py --last   # view the most recent decision
    python scripts/r4_shadow_diagnostics.py --min-selector-version 0.2.2  # clean post-upgrade sample
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from eigencapital.shadow.portfolio.selector import (  # noqa: E402
    HARD_CAP_REASONS,
    ShadowSelectorConfig,
)

SIZE_NS = (1, 2, 4, 6, 8)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def _mean(vals: List[float]) -> float:
    vals = [v for v in vals if v is not None and isinstance(v, (int, float)) and v == v]
    return float(np.mean(vals)) if vals else 0.0


def edge_by_size(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D1: per selection size, average edge retained / vol / max|corr|."""
    rows = []
    for n in [0] + list(range(1, 9)):
        edge, vol, maxc, q = [], [], [], []
        for d in decisions:
            chain = d.get("chain_by_n", {})
            node = chain.get(str(n))
            if node is None:
                continue
            edge.append(node["metrics"]["gross_edge"] / d["baseline"]["metrics"]["gross_edge"])
            vol.append(node["metrics"]["portfolio_vol_annual"])
            maxc.append(node["metrics"]["max_abs_pairwise_corr"])
            q.append(node["quality"])
        if edge:
            rows.append(
                {
                    "size": n,
                    "avg_edge_retained_pct": round(100.0 * _mean(edge), 2),
                    "avg_portfolio_vol": round(_mean(vol), 4),
                    "avg_max_abs_corr": round(_mean(maxc), 4),
                    "avg_quality": round(_mean(q), 4),
                    "days_reaching_n": len(edge),
                }
            )
    return {"by_size": rows}


def lost_edge_attribution(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D2: charge every R4-only name's |w| to the TRUE final-state reason.

    The recorded dominant_rejection can be stale (R4-S 2026-09-08): a
    candidate that tripped a hard cap in an early greedy trial — e.g.
    {XAUUSD, AUDUSD} → 84% safe_haven — was labeled factor_concentration
    even though no final-state trial violated. Attribution therefore
    RECOMPUTES the hard-cap status against the decision's FINAL selected
    weights. A name that genuinely violates the final portfolio is charged
    to that cap; a name whose final state is clean is charged to capacity
    (or its recorded non-cap reason), never to a stale concentration label.
    """
    exposure = ShadowSelectorConfig().exposure_config()
    attribution: Dict[str, float] = defaultdict(float)
    substituted: float = 0.0  # shadow picks outside R4's top-20
    total_lost: float = 0.0
    total_r4: float = 0.0
    for d in decisions:
        baseline_set = set(d["baseline"]["symbols"])
        selected_set = set(d["selected"]["symbols"])
        final_weights = d["selected"].get("weights", {})
        r4_gross = d["baseline"]["metrics"]["gross_edge"]
        total_r4 += r4_gross
        for c in d["candidates"]:
            if c["symbol"] in baseline_set and c["symbol"] not in selected_set:
                lost = abs(c["weight"])
                total_lost += lost
                hard = exposure.final_state_rejection(final_weights, c["symbol"], c["weight"])
                if hard is not None:
                    reason = hard
                else:
                    recorded = c.get("dominant_rejection") or c.get("rejection_reason")
                    if recorded in HARD_CAP_REASONS:
                        # Stale label from an early trial — final state is clean.
                        reason = "portfolio_capacity"
                    else:
                        reason = recorded or "portfolio_capacity"
                attribution[reason] += lost
            if c["symbol"] not in baseline_set and c["symbol"] in selected_set:
                substituted += abs(c["weight"])
    attribution_pct = {
        k: round(100.0 * v / total_lost, 2) if total_lost else 0.0
        for k, v in sorted(attribution.items(), key=lambda x: -x[1])
    }
    return {
        "total_r4_edge": round(total_r4, 3),
        "total_lost_edge": round(total_lost, 3),
        "edge_lost_pct": round(100.0 * total_lost / total_r4, 2) if total_r4 else 0.0,
        "by_reason": attribution_pct,
        "substituted_edge_outside_r4_top": round(substituted, 3),
    }


def frontier(decisions: List[Dict[str, Any]], size_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D3: R4 vs shadow chain — decision-time metrics + realized (gross/net)."""
    # Realized aggregates per N from the size-breakdown evidence.
    per_n: Dict[int, Dict[str, Any]] = {}
    for row in size_rows:
        n = row["size"]
        b = per_n.setdefault(n, {"pnl": 0.0, "cost": 0.0, "rs": [], "exits": 0, "days": 0})
        b["pnl"] += row["gross_pnl"]
        b["cost"] += row["cost"]
        b["days"] += 1
        if row.get("avg_r") is not None:
            b["rs"].append(row["avg_r"])
        b["exits"] += row.get("n_exits", 0)

    avg_r4 = {
        "avg_edge": 1.0,
        "avg_portfolio_vol": _mean([d["baseline"]["metrics"]["portfolio_vol_annual"] for d in decisions]),
        "avg_max_abs_corr": _mean([d["baseline"]["metrics"]["max_abs_pairwise_corr"] for d in decisions]),
    }
    rows = []
    for n in SIZE_NS:
        node_rows = [d["chain_by_n"].get(str(n)) for d in decisions if str(n) in d.get("chain_by_n", {})]
        node_rows = [r for r in node_rows if r]
        if not node_rows:
            continue
        realized = per_n.get(n, {})
        rs = realized.get("rs", [])
        rows.append(
            {
                "size": n,
                "avg_edge_retained_pct": round(
                    100.0
                    * _mean(
                        [
                            r["metrics"]["gross_edge"] / d["baseline"]["metrics"]["gross_edge"]
                            for d, r in zip(decisions, node_rows)
                            if d["baseline"]["metrics"]["gross_edge"] > 0
                        ]
                    ),
                    2,
                ),
                "avg_portfolio_vol": round(_mean([r["metrics"]["portfolio_vol_annual"] for r in node_rows]), 4),
                "avg_max_abs_corr": round(_mean([r["metrics"]["max_abs_pairwise_corr"] for r in node_rows]), 4),
                "realized_total_pnl_gross": round(realized.get("pnl", 0.0), 2),
                "realized_total_cost": round(realized.get("cost", 0.0), 2),
                "realized_total_pnl_net": round(realized.get("pnl", 0.0) - realized.get("cost", 0.0), 2),
                "realized_avg_r": round(float(np.mean(rs)), 4) if rs else None,
                "realized_exits": realized.get("exits", 0),
            }
        )
    return {"r4": avg_r4, "by_size": rows}


def pretty_print_decision(decision: Dict[str, Any]) -> None:
    """Pretty-print a single shadow decision record (the --last viewer)."""
    selected_syms = decision["selected"]["symbols"]
    weights = decision["selected"].get("weights", {})
    by_sym = {c["symbol"]: c for c in decision["candidates"]}
    sel_set = set(selected_syms)

    print("═" * 74)
    print(f"R4-S DECISION  {decision.get('cycle_id', '?')}")
    print("═" * 74)
    print(
        f"  status: {decision.get('status')}  |  signal: {decision.get('signal_date')}  |  "
        f"recorded: {str(decision.get('record_timestamp', ''))[:19]}"
    )
    print(
        f"  selector: {decision.get('selector_version')}  |  "
        f"config_hash: {str(decision.get('config_hash', ''))[:12]}"
    )

    print(f"\n  SELECTED ({len(selected_syms)})")
    print(f"  {'rank':<5}{'symbol':<10}{'dir':<6}{'weight':<9}{'vol':<8}{'class':<10}{'factor'}")
    print("  " + "─" * 60)
    for s in selected_syms:
        c = by_sym.get(s, {})
        vol = c.get("annualized_vol")
        print(
            f"  {c.get('r4_rank', '?'):!s:<5}{s:<10}{c.get('direction', '?'):!s:<6}"
            f"{weights.get(s, 0):+.4f}  {vol if vol is not None else 0.0:.1%}   "
            f"{c.get('asset_class', '?'):!s:<10}{c.get('factor_group', '?')}"
        )

    rejected = [c for c in decision["candidates"] if c["symbol"] not in sel_set]
    print(f"\n  REJECTED ({len(rejected)})")
    for c in rejected:
        reason = c.get("dominant_rejection") or c.get("rejection_reason") or "-"
        print(f"  #{c.get('r4_rank', '?'):!s:<3} {c['symbol']:<10} {reason}")

    e = decision.get("edge_metrics", {})
    sel_m = decision["selected"]["metrics"]
    base_m = decision["baseline"]["metrics"]
    print("\n  EDGE & RISK vs R4 BASELINE")
    print(
        f"  edge retained: {e.get('edge_retained_pct')}%  |  "
        f"top-signal: {e.get('top_signal_retention')}"
    )
    print(
        f"  avg pairwise corr: R4={base_m.get('avg_pairwise_corr'):.4f} "
        f"shadow={sel_m.get('avg_pairwise_corr'):.4f}"
    )
    print(
        f"  portfolio vol:     R4={base_m.get('portfolio_vol_annual'):.4f} "
        f"shadow={sel_m.get('portfolio_vol_annual'):.4f}"
    )
    print(
        f"  effective pos:     R4={base_m.get('effective_positions'):.1f} "
        f"shadow={sel_m.get('effective_positions'):.1f}"
    )
    print(
        f"  max cluster:       R4={base_m.get('exposure', {}).get('max_cluster_exposure', {}).get('pct', 0):.1%} "
        f"shadow={sel_m.get('exposure', {}).get('max_cluster_exposure', {}).get('pct', 0):.1%}"
    )
    print(
        f"  max ccy:           R4={base_m.get('exposure', {}).get('max_currency_exposure', {}).get('pct', 0):.1%} "
        f"shadow={sel_m.get('exposure', {}).get('max_currency_exposure', {}).get('pct', 0):.1%}"
    )


def _to_pct(v: float | None) -> float | None:
    """Fraction → percentage units; None stays None."""
    return v * 100.0 if v is not None else None


def _metric_at(metrics: Dict[str, Any], path: str) -> float | None:
    """Navigate a dotted path into a metrics dict, e.g.
    'exposure.max_cluster_exposure.pct'. Returns None when missing."""
    cur: Any = metrics
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, (int, float)) else None


def _avg_over(decisions: List[Dict[str, Any]], fn) -> float | None:
    """Mean of fn(d) across decisions; None when no decision yields a value."""
    vals = []
    for d in decisions:
        v = fn(d)
        if v is not None and v == v:  # skip NaN
            vals.append(v)
    return float(np.mean(vals)) if vals else None


# (key, label, format) — the evidence table rows. Format is one of
# pct / float2 / float4 / float6 / dash. Realized R is populated from the
# size-breakdown ledger when present; drawdown and turnover need
# account-level tracking across cycles and stay "—" until that exists.
COMPARATIVE_ROWS = [
    ("signal_retained_pct", "Signal retained", "pct"),
    ("portfolio_vol_annual", "Portfolio volatility (annual)", "float4"),
    ("portfolio_variance", "Portfolio variance", "float6"),
    ("max_ccy", "Max currency concentration", "pct"),
    ("max_factor", "Factor concentration", "pct"),
    ("effective_bets", "Effective bet count", "float2"),
    ("gross", "Gross exposure", "float4"),
    ("net", "Net exposure", "float4"),
    ("risk_contrib_hhi", "Risk contribution concentration (HHI)", "float4"),
    ("risk_contrib_max", "Max risk contribution share", "pct"),
    ("realized_r", "Realized R", "float4"),
    ("drawdown", "Drawdown", "dash"),
    ("turnover", "Turnover", "dash"),
]

COMPARATIVE_SIZES = [4, 5, 6, 7, 8]


def comparative_evidence(
    decisions: List[Dict[str, Any]],
    size_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """R4-20 vs Shadow-4..8 comparative table (the verdict evidence table).

    Rows are metrics; columns are portfolio sizes. Decision-time metrics are
    averaged across cycles from chain_by_n — the SAME calculator measures the
    R4 baseline and every shadow prefix, so the comparison is apples-to-apples.
    Realized R comes from the size-breakdown ledger when present. Drawdown and
    turnover are reported as pending ('—').
    """

    def edge_retained(d: Dict[str, Any], n: int) -> float | None:
        base = d["baseline"]["metrics"].get("gross_edge", 0.0)
        node = d["chain_by_n"].get(str(n))
        if base and node:
            return 100.0 * node["metrics"]["gross_edge"] / base
        return None

    def chain_metric(d: Dict[str, Any], n: int, path: str) -> float | None:
        node = d["chain_by_n"].get(str(n))
        return _metric_at(node["metrics"], path) if node else None

    def base_metric(d: Dict[str, Any], path: str) -> float | None:
        return _metric_at(d["baseline"]["metrics"], path)

    def var_of(vol: float | None) -> float | None:
        return vol**2 if vol is not None else None

    realized_by_n: Dict[int, List[float]] = {}
    for row in size_rows:
        n = row.get("size")
        if n is not None and row.get("avg_r") is not None:
            realized_by_n.setdefault(n, []).append(row["avg_r"])

    table: Dict[str, Any] = {}
    for key, _label, _fmt in COMPARATIVE_ROWS:
        table[key] = {"r4_20": None, **{f"s{n}": None for n in COMPARATIVE_SIZES}}

    def fill(n: int, path: str) -> None:
        table["portfolio_vol_annual"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: chain_metric(d, n, path)
        )
        table["portfolio_variance"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: var_of(chain_metric(d, n, path))
        )
        # exposure pct values are stored as fractions (0.1262) — normalize to
        # percentage units so every "pct" row in the table is consistent.
        table["max_ccy"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: _to_pct(chain_metric(d, n, "exposure.max_currency_exposure.pct"))
        )
        table["max_factor"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: _to_pct(chain_metric(d, n, "exposure.max_cluster_exposure.pct"))
        )
        table["effective_bets"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: chain_metric(d, n, "effective_positions")
        )
        table["gross"][f"s{n}"] = _avg_over(decisions, lambda d, n=n: chain_metric(d, n, "gross_edge"))
        table["net"][f"s{n}"] = _avg_over(decisions, lambda d, n=n: chain_metric(d, n, "net_edge"))
        table["risk_contrib_hhi"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: chain_metric(d, n, "risk_contribution_hhi")
        )
        table["risk_contrib_max"][f"s{n}"] = _avg_over(
            decisions, lambda d, n=n: _to_pct(chain_metric(d, n, "max_risk_contribution_share"))
        )
        r = realized_by_n.get(n)
        table["realized_r"][f"s{n}"] = float(np.mean(r)) if r else None

    for n in COMPARATIVE_SIZES:
        table["signal_retained_pct"][f"s{n}"] = _avg_over(decisions, lambda d, n=n: edge_retained(d, n))
        fill(n, "portfolio_vol_annual")

    table["signal_retained_pct"]["r4_20"] = 100.0
    table["portfolio_vol_annual"]["r4_20"] = _avg_over(decisions, lambda d: base_metric(d, "portfolio_vol_annual"))
    table["portfolio_variance"]["r4_20"] = _avg_over(decisions, lambda d: var_of(base_metric(d, "portfolio_vol_annual")))
    table["max_ccy"]["r4_20"] = _avg_over(
        decisions, lambda d: _to_pct(base_metric(d, "exposure.max_currency_exposure.pct"))
    )
    table["max_factor"]["r4_20"] = _avg_over(
        decisions, lambda d: _to_pct(base_metric(d, "exposure.max_cluster_exposure.pct"))
    )
    table["effective_bets"]["r4_20"] = _avg_over(decisions, lambda d: base_metric(d, "effective_positions"))
    table["gross"]["r4_20"] = _avg_over(decisions, lambda d: base_metric(d, "gross_edge"))
    table["net"]["r4_20"] = _avg_over(decisions, lambda d: base_metric(d, "net_edge"))
    table["risk_contrib_hhi"]["r4_20"] = _avg_over(decisions, lambda d: base_metric(d, "risk_contribution_hhi"))
    table["risk_contrib_max"]["r4_20"] = _avg_over(
        decisions, lambda d: _to_pct(base_metric(d, "max_risk_contribution_share"))
    )
    return table


def print_comparative(table: Dict[str, Any]) -> None:
    """Render the R4-20 vs Shadow-4..8 comparative evidence table."""
    print("\n[D3b] COMPARATIVE EVIDENCE — R4-20 vs SHADOW-4..8 (avg per cycle, decision-time)")
    header = f"  {'metric':<34}{'R4-20':>10}" + "".join(f"{f'S-{n}':>10}" for n in COMPARATIVE_SIZES)
    print(header)
    print("  " + "─" * (len(header) - 2))

    def fmt_val(v: float | None, kind: str) -> str:
        if v is None:
            return f"{'—':>10}"
        if kind == "pct":
            return f"{v:>9.1f}%"
        if kind == "float2":
            return f"{v:>10.2f}"
        if kind == "float4":
            return f"{v:>10.4f}"
        if kind == "float6":
            return f"{v:>10.6f}"
        return f"{'—':>10}"

    for key, label, kind in COMPARATIVE_ROWS:
        cells = [table[key]["r4_20"]] + [table[key][f"s{n}"] for n in COMPARATIVE_SIZES]
        print(f"  {label:<34}" + "".join(fmt_val(v, kind) for v in cells))


def marginal_efficiency(table: Dict[str, Any]) -> Dict[str, Any]:
    """D3c: signal efficiency across the chain — where do diminishing returns begin?

    For each additional position (transition S(n) → S(n+1)):
        Δsignal retained (pp) / Δportfolio variance
    plus the level ratio signal/variance per size. Only transitions where both
    terms are available are reported; None values (e.g. pre-0.2.2 records
    missing a metric) are skipped rather than treated as zero.

    Decision-time only: signal retained is NOT realized return and modeled
    variance is NOT realized risk, so this table informs the question "where
    does additional R4 signal become inefficient relative to incremental
    modeled risk?" — it is not a promotion criterion by itself.
    """
    sizes = ["r4_20"] + [f"s{n}" for n in COMPARATIVE_SIZES]
    labels = {f"s{n}": f"S-{n}" for n in COMPARATIVE_SIZES}
    labels["r4_20"] = "R4-20"

    levels = []
    for key in sizes:
        sig = table["signal_retained_pct"].get(key)
        var = table["portfolio_variance"].get(key)
        if sig is None or var is None or var <= 0:
            continue
        levels.append(
            {
                "size": labels[key],
                "signal_retained_pct": round(sig, 2),
                "portfolio_variance": round(var, 6),
                "signal_per_variance": round(sig / var, 1),
            }
        )

    transitions = []
    for i in range(1, len(sizes)):
        prev, cur = sizes[i - 1], sizes[i]
        sig_prev = table["signal_retained_pct"].get(prev)
        sig_cur = table["signal_retained_pct"].get(cur)
        var_prev = table["portfolio_variance"].get(prev)
        var_cur = table["portfolio_variance"].get(cur)
        if None in (sig_prev, sig_cur, var_prev, var_cur) or var_cur is None or var_prev is None:
            continue
        d_var = var_cur - var_prev
        d_sig = sig_cur - sig_prev
        if d_var <= 0:
            # Variance did not rise (or data is flat): efficiency is unbounded,
            # report the signal gain with a marker rather than a bogus ratio.
            efficiency = None if d_var == 0 else float("inf")
        else:
            efficiency = round(d_sig / (d_var * 10000.0), 2)  # pp per 1e-4 variance
        transitions.append(
            {
                "transition": f"{labels[prev]} → {labels[cur]}",
                "d_signal_pp": round(d_sig, 2),
                "d_variance": round(d_var, 6),
                "efficiency_pp_per_1e4_var": efficiency,
            }
        )
    return {"levels": levels, "transitions": transitions}


def print_efficiency(eff: Dict[str, Any]) -> None:
    """Render the D3c signal-efficiency table."""
    print("\n[D3c] SIGNAL / RISK EFFICIENCY (decision-time; signal ≠ return)")
    print(f"  {'size':<8}{'signal':>10}{'variance':>12}{'signal/var':>12}")
    for r in eff["levels"]:
        print(
            f"  {r['size']:<8}{r['signal_retained_pct']:>9.1f}%{r['portfolio_variance']:>12.6f}"
            f"{r['signal_per_variance']:>12.1f}"
        )
    print(f"  {'transition':<16}{'Δsignal':>10}{'Δvariance':>12}{'efficiency':>12}")
    for t in eff["transitions"]:
        e = t["efficiency_pp_per_1e4_var"]
        e_str = f"{e:>12.2f}" if e is not None and e != float("inf") else f"{'∞':>12}"
        print(
            f"  {t['transition']:<16}{t['d_signal_pp']:>+9.2f}pp{t['d_variance']:>+12.6f}{e_str}"
        )


_SELVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(version: str) -> Tuple[int, int, int] | None:
    """Parse a selector version into a comparable tuple.

    Accepts either the full record value ("r4s-shadow-selector-0.2.2") or a
    bare semver ("0.2.2"). Returns None when unparseable.
    """
    m = _SELVER_RE.search(version)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def filter_by_selector_version(
    decisions: List[Dict[str, Any]],
    min_version: str | None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Keep only decisions whose selector_version >= min_version.

    Records from before the v0.2.2 upgrade lack risk-contribution metrics;
    mixing them with post-upgrade records as if identical measurements would
    corrupt the comparative evidence (R4-S verdict: clean evaluation boundary
    PRE-v0.2.2 / v0.2.2 qualification set). Decisions with an unparseable
    version are kept only when no minimum is requested.

    Returns (filtered, dropped_count).
    """
    if not min_version:
        return decisions, 0
    target = _version_tuple(min_version)
    if target is None:
        raise ValueError(f"cannot parse selector version: {min_version!r}")
    kept, dropped = [], 0
    for d in decisions:
        v = _version_tuple(d.get("selector_version", ""))
        if v is not None and v >= target:
            kept.append(d)
        else:
            dropped += 1
    return kept, dropped


# R4-20 control column size in the size-breakdown ledger (mirrors
# BASELINE_SIZE in scripts/r4_shadow_portfolio.py).
R4_BASELINE_SIZE = 20

# D4 realized-outcome rows: (key, label, kind). kind is one of
# pct / float2 / float4 / dash (see print_comparative).
REALIZED_ROWS = [
    ("signal_retained_pct", "Signal retained", "pct"),
    ("realized_pnl", "Realized P&L (net)", "float2"),
    ("realized_r", "Realized R (avg)", "float4"),
    ("sharpe", "Sharpe (per-cycle)", "float2"),
    ("max_dd", "Max DD", "float2"),
    ("realized_vol", "Realized volatility", "float4"),
    ("downside_dev", "Downside deviation", "float4"),
    ("worst_cycle", "Worst cycle", "float2"),
    ("tail_loss", "Tail loss (p5)", "float2"),
    ("turnover", "Turnover (avg/cycle)", "float4"),
    ("cost", "Estimated costs", "float2"),
    ("net_r_after_costs", "Net R after costs", "dash"),
    ("erc", "Effective risk contributors", "float2"),
    ("max_risk_contribution", "Max risk contribution", "pct"),
]


def _max_drawdown(series: List[float]) -> float | None:
    if not series:
        return None
    cum = np.cumsum(series)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def _per_cycle_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Distributional realized stats from one size's per-cycle ledger rows."""
    net = [r["net_pnl"] for r in rows if r.get("net_pnl") is not None]
    gross = [r["gross_pnl"] for r in rows if r.get("gross_pnl") is not None]
    cost = [r["cost"] for r in rows if r.get("cost") is not None]
    rs = [r["avg_r"] for r in rows if r.get("n_exits") and r.get("avg_r") is not None]
    turn = [r["turnover"] for r in rows if r.get("turnover") is not None]
    out: Dict[str, Any] = {"cycles": len(rows)}
    out["realized_pnl"] = round(sum(net), 2) if net else None
    out["realized_r"] = round(float(np.mean(rs)), 4) if rs else None
    out["sharpe"] = None
    out["max_dd"] = _max_drawdown(net) if net else None
    out["realized_vol"] = None
    out["downside_dev"] = None
    out["worst_cycle"] = round(min(net), 2) if net else None
    out["tail_loss"] = round(float(np.percentile(net, 5)), 2) if len(net) >= 2 else None
    out["turnover"] = round(float(np.mean(turn)), 4) if turn else None
    out["cost"] = round(sum(cost), 2) if cost else None
    out["net_r_after_costs"] = None  # needs per-exit cost attribution; see note
    out["_gross"] = sum(gross) if gross else None
    if len(net) >= 2 and float(np.std(net)) > 0:
        sd = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
        if sd > 0:
            out["sharpe"] = round(float(np.mean(net)) / sd * np.sqrt(252.0), 2)
            out["realized_vol"] = round(sd * np.sqrt(252.0), 4)
            neg = np.minimum(np.array(net), 0.0)
            out["downside_dev"] = round(float(np.sqrt(np.mean(neg**2))) * np.sqrt(252.0), 4)
    return out


def realized_outcomes(
    decisions: List[Dict[str, Any]],
    size_rows: List[Dict[str, Any]],
    comparative: Dict[str, Any],
) -> Dict[str, Any]:
    """D4: realized-outcome evaluation — R4-20 vs Shadow-4..8.

    Uses the per-cycle size ledger (shadow_portfolio_size_breakdown.jsonl) so
    every size is measured under identical conventions: same decision-bar
    entry/exit, weight-space notional |w|·equity, and the project's 10 bps
    per-side cost. R4-20 is the frozen R4 baseline tracked under the same
    rules. Total P&L / cost span ALL ledger rows (including the terminal END
    liquidation, matching D3's frontier totals); Sharpe / vol / downside /
    tail are per-cycle distributional statistics on net P&L over decision
    rows only (annualized with √252 over decision days — a proxy, documented,
    not realized daily returns).

    Net R after costs is intentionally '—': avg_r is in ATR multiples while
    costs are dollar notional charges, so a defensible per-exit net-R needs
    per-exit cost attribution not present in the ledger.
    """
    # Cycle rows exclude the terminal "END" liquidation (a lump-sum close-out,
    # not a decision cycle) so per-cycle distributional stats stay honest.
    by_size: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in size_rows:
        n = row.get("size")
        if n is not None and str(row.get("signal_date", "")).upper() != "END":
            by_size[n].append(row)
    # All rows (incl. END) for total P&L / cost — matches D3's frontier totals.
    by_size_all: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in size_rows:
        n = row.get("size")
        if n is not None:
            by_size_all[n].append(row)

    cols = ["r4_20"] + [f"s{n}" for n in COMPARATIVE_SIZES]
    table: Dict[str, Any] = {}
    for key, _label, _kind in REALIZED_ROWS:
        table[key] = {c: None for c in cols}

    # Signal retained and ERC come from decision-time chain metrics (ERC only
    # exists post-0.2.2).
    def chain_mean(n: int, path: str) -> float | None:
        vals = []
        for d in decisions:
            node = d["chain_by_n"].get(str(n))
            v = _metric_at(node["metrics"], path) if node else None
            if v is not None:
                vals.append(v)
        return float(np.mean(vals)) if vals else None

    def chain_mean_pct(n: int, path: str) -> float | None:
        v = chain_mean(n, path)
        return round(v * 100.0, 2) if v is not None else None

    for n in COMPARATIVE_SIZES:
        table["signal_retained_pct"][f"s{n}"] = comparative["signal_retained_pct"].get(f"s{n}")
        table["erc"][f"s{n}"] = chain_mean(n, "effective_risk_contributors")
        table["max_risk_contribution"][f"s{n}"] = chain_mean_pct(n, "max_risk_contribution_share")
        stats = _per_cycle_stats(by_size.get(n, []))
        for key in ("realized_r", "sharpe", "max_dd", "realized_vol", "downside_dev",
                    "worst_cycle", "tail_loss", "turnover", "net_r_after_costs"):
            table[key][f"s{n}"] = stats.get(key)
        # Total P&L / cost span ALL rows incl. END (matches D3 frontier totals).
        all_rows = by_size_all.get(n, [])
        table["realized_pnl"][f"s{n}"] = _round_sum(all_rows, "net_pnl")
        table["cost"][f"s{n}"] = _round_sum(all_rows, "cost")

    table["signal_retained_pct"]["r4_20"] = comparative["signal_retained_pct"].get("r4_20")
    # R4-20 ERC / max-risk-contribution come from baseline metrics (chain_by_n
    # only holds shadow sizes); only present in v0.2.2+ records.
    erc_vals = [
        v
        for d in decisions
        if (v := _metric_at(d["baseline"]["metrics"], "effective_risk_contributors")) is not None
    ]
    table["erc"]["r4_20"] = round(float(np.mean(erc_vals)), 2) if erc_vals else None
    mrc_vals = [
        v
        for d in decisions
        if (v := _metric_at(d["baseline"]["metrics"], "max_risk_contribution_share")) is not None
    ]
    table["max_risk_contribution"]["r4_20"] = round(float(np.mean(mrc_vals)) * 100.0, 2) if mrc_vals else None
    base_stats = _per_cycle_stats(by_size.get(R4_BASELINE_SIZE, []))
    for key in ("realized_r", "sharpe", "max_dd", "realized_vol", "downside_dev",
                "worst_cycle", "tail_loss", "turnover", "net_r_after_costs"):
        table[key]["r4_20"] = base_stats.get(key)
    base_all = by_size_all.get(R4_BASELINE_SIZE, [])
    table["realized_pnl"]["r4_20"] = _round_sum(base_all, "net_pnl")
    table["cost"]["r4_20"] = _round_sum(base_all, "cost")
    return table


def _round_sum(rows: List[Dict[str, Any]], key: str) -> float | None:
    """Sum a field across rows; None only when no row carries the field."""
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(float(sum(vals)), 2) if vals else None


def print_realized(table: Dict[str, Any]) -> None:
    """Render the D4 realized-outcome table."""
    print("\n[D4] REALIZED-OUTCOME EVALUATION — R4-20 vs SHADOW-4..8 (per-cycle ledger)")
    header = f"  {'metric':<34}{'R4-20':>10}" + "".join(f"{f'S-{n}':>10}" for n in COMPARATIVE_SIZES)
    print(header)
    print("  " + "─" * (len(header) - 2))

    def fmt_val(v: Any, kind: str) -> str:
        if v is None:
            return f"{'—':>10}"
        if kind == "pct":
            return f"{v:>9.1f}%"
        if kind == "float2":
            return f"{v:>10.2f}"
        if kind == "float4":
            return f"{v:>10.4f}"
        return f"{'—':>10}"

    for key, label, kind in REALIZED_ROWS:
        cells = [table[key]["r4_20"]] + [table[key][f"s{n}"] for n in COMPARATIVE_SIZES]
        print(f"  {label:<34}" + "".join(fmt_val(v, kind) for v in cells))


def regime_interaction(decisions: List[Dict[str, Any]], outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D5: bucket decision days by vol_ratio = vol_now / vol_median (terciles)."""
    ratios = sorted(d["regime"]["vol_ratio"] for d in decisions if d.get("regime", {}).get("vol_ratio") is not None)
    if len(ratios) < 3:
        return {"note": "insufficient regime data", "buckets": []}
    q1 = ratios[len(ratios) // 3]
    q2 = ratios[2 * len(ratios) // 3]

    outcome_by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in outcomes:
        outcome_by_date[o["signal_date"]].append(o)

    buckets = []
    for label, lo, hi in (("low_vol", None, q1), ("med_vol", q1, q2), ("high_vol", q2, None)):
        group = [
            d
            for d in decisions
            if (lo is None or d["regime"]["vol_ratio"] > lo) and (hi is None or d["regime"]["vol_ratio"] <= hi)
        ]
        if not group:
            continue
        pnls, rs = [], []
        for d in group:
            for o in outcome_by_date.get(d["signal_date"], []):
                if o.get("shadow_pnl") is not None:
                    pnls.append(o["shadow_pnl"])
                if o.get("shadow_r") is not None:
                    rs.append(o["shadow_r"])
        buckets.append(
            {
                "bucket": label,
                "vol_ratio_range": [round(lo, 3) if lo is not None else None, round(hi, 3) if hi is not None else None],
                "days": len(group),
                "avg_size": round(_mean([len(d["selected"]["symbols"]) for d in group]), 2),
                "avg_edge_retained_pct": round(_mean([d["edge_metrics"]["edge_retained_pct"] for d in group]), 2),
                "avg_portfolio_vol": round(_mean([d["selected"]["metrics"]["portfolio_vol_annual"] for d in group]), 4),
                "realized_pnl": round(sum(pnls), 2),
                "realized_avg_r": round(float(np.mean(rs)), 4) if rs else None,
                "realized_hit_rate": f"{sum(1 for r in rs if r > 0)}/{len(rs)}" if rs else "0/0",
            }
        )
    return {"buckets": buckets}


def main() -> int:
    parser = argparse.ArgumentParser(description="R4-S shadow diagnostics (research, not optimization)")
    parser.add_argument("--out-dir", default="reports/r4_loop")
    parser.add_argument(
        "--last",
        action="store_true",
        help="pretty-print the most recent shadow decision and exit",
    )
    parser.add_argument(
        "--min-selector-version",
        default=None,
        help="only analyze decisions whose selector_version >= this (e.g. 0.2.2); "
        "creates a clean evaluation boundary so pre/post-upgrade metrics are "
        "never mixed (risk-contribution fields only exist from v0.2.2)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    decisions = load_jsonl(out_dir / "shadow_portfolio_decisions.jsonl")
    if not decisions:
        print(f"no shadow decisions found in {out_dir}")
        return 2

    try:
        decisions, dropped = filter_by_selector_version(decisions, args.min_selector_version)
    except ValueError as e:
        print(f"invalid --min-selector-version: {e}")
        return 2
    if args.min_selector_version and not decisions:
        print(f"no decisions at selector_version >= {args.min_selector_version} in {out_dir}")
        return 2

    if args.last:
        pretty_print_decision(decisions[-1])
        return 0

    outcomes = load_jsonl(out_dir / "shadow_portfolio_outcomes.jsonl")
    size_rows = load_jsonl(out_dir / "shadow_portfolio_size_breakdown.jsonl")

    d1 = edge_by_size(decisions)
    d2 = lost_edge_attribution(decisions)
    d3 = frontier(decisions, size_rows)
    d3b = comparative_evidence(decisions, size_rows)
    d3c = marginal_efficiency(d3b)
    d4 = realized_outcomes(decisions, size_rows, d3b)
    d5 = regime_interaction(decisions, outcomes)

    print("═" * 74)
    print("R4-S DIAGNOSTICS — where does the lost edge go?")
    print("═" * 74)
    if args.min_selector_version:
        print(f"  evaluation boundary: selector_version >= {args.min_selector_version} "
              f"({len(decisions)} decisions, {dropped} pre-boundary dropped)")

    print("\n[D1] EDGE RETAINED BY SELECTION SIZE")
    print(f"  {'size':<6}{'days':<7}{'edge ret %':<12}{'port vol':<10}{'max |corr|':<12}{'quality'}")
    for r in d1["by_size"]:
        print(
            f"  {r['size']:<6}{r['days_reaching_n']:<7}{r['avg_edge_retained_pct']:<12}{r['avg_portfolio_vol']:<10}{r['avg_max_abs_corr']:<12}{r['avg_quality']}"
        )

    print("\n[D2] LOST-EDGE ATTRIBUTION (R4 names excluded by shadow — final-state reason)")
    print(f"  total R4 edge: {d2['total_r4_edge']} | lost: {d2['total_lost_edge']} ({d2['edge_lost_pct']}%)")
    for reason, pct in d2["by_reason"].items():
        print(f"  {reason:<28}{pct:>8.2f}%")
    print(f"  edge substituted from OUTSIDE R4's top-20: {d2['substituted_edge_outside_r4_top']}")

    print("\n[D3] RISK/EDGE FRONTIER (R4 vs shadow chain)")
    r4 = d3["r4"]
    print(f"  R4 (20): edge 100% | vol {r4['avg_portfolio_vol']:.4f} | max|corr| {r4['avg_max_abs_corr']:.4f}")
    print(
        f"  {'size':<6}{'edge ret %':<12}{'port vol':<10}{'max |corr|':<12}{'realized gross':<16}{'net of cost':<14}{'avg R':<8}{'exits'}"
    )
    for r in d3["by_size"]:
        print(
            f"  {r['size']:<6}{r['avg_edge_retained_pct']:<12}{r['avg_portfolio_vol']:<10}{r['avg_max_abs_corr']:<12}"
            f"{r['realized_total_pnl_gross']:<16}{r['realized_total_pnl_net']:<14}{r['realized_avg_r']!s:<8}{r['realized_exits']}"
        )

    print_comparative(d3b)
    print_efficiency(d3c)
    print_realized(d4)

    print("\n[D5] REGIME INTERACTION (vol_now/vol_median terciles)")
    print(
        f"  {'bucket':<10}{'ratio':<14}{'days':<6}{'size':<6}{'edge ret %':<12}{'port vol':<10}{'real PnL':<12}{'avg R':<8}{'hit'}"
    )
    for b in d5["buckets"]:
        rng = f"{b['vol_ratio_range'][0]}–{b['vol_ratio_range'][1]}"
        print(
            f"  {b['bucket']:<10}{rng:<14}{b['days']:<6}{b['avg_size']:<6}{b['avg_edge_retained_pct']:<12}"
            f"{b['avg_portfolio_vol']:<10}{b['realized_pnl']:<12}{b['realized_avg_r']!s:<8}{b['realized_hit_rate']}"
        )

    summary = {
        "edge_by_size": d1,
        "lost_edge": d2,
        "frontier": d3,
        "comparative": d3b,
        "efficiency": d3c,
        "realized": d4,
        "regime": d5,
        "evaluation_boundary": args.min_selector_version,
        "decisions_in_sample": len(decisions),
    }
    out = out_dir / "shadow_diagnostics_summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsummary → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
