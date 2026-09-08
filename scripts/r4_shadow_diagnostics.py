"""R4-S Diagnostics — where does the lost edge go, and is there a stable
risk/edge frontier?

Reads the shadow evidence produced by scripts/r4_shadow_portfolio.py and
computes the four diagnostic analyses (research phase, NOT optimization):

  D1. Edge retained by selection size (top-1/2/4/6/8) — where edge collapses.
  D2. Lost-edge attribution — every R4 name excluded by the shadow portfolio
      is charged to one dominant measurable reason.
  D3. Risk/edge frontier — R4 vs shadow chain P_1..P_8, gross AND net of the
      project's 10 bps/side cost convention, plus realized outcomes.
  D4. Regime interaction — decision days bucketed by vol_now/vol_median.

Outputs:
    printed tables + reports/r4_loop/shadow_diagnostics_summary.json

Usage:
    python scripts/r4_shadow_diagnostics.py [--out-dir reports/r4_loop]
    python scripts/r4_shadow_diagnostics.py --last   # view the most recent decision
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

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


def regime_interaction(decisions: List[Dict[str, Any]], outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """D4: bucket decision days by vol_ratio = vol_now / vol_median (terciles)."""
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
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    decisions = load_jsonl(out_dir / "shadow_portfolio_decisions.jsonl")
    if not decisions:
        print(f"no shadow decisions found in {out_dir}")
        return 2

    if args.last:
        pretty_print_decision(decisions[-1])
        return 0

    outcomes = load_jsonl(out_dir / "shadow_portfolio_outcomes.jsonl")
    size_rows = load_jsonl(out_dir / "shadow_portfolio_size_breakdown.jsonl")

    d1 = edge_by_size(decisions)
    d2 = lost_edge_attribution(decisions)
    d3 = frontier(decisions, size_rows)
    d4 = regime_interaction(decisions, outcomes)

    print("═" * 74)
    print("R4-S DIAGNOSTICS — where does the lost edge go?")
    print("═" * 74)

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

    print("\n[D4] REGIME INTERACTION (vol_now/vol_median terciles)")
    print(
        f"  {'bucket':<10}{'ratio':<14}{'days':<6}{'size':<6}{'edge ret %':<12}{'port vol':<10}{'real PnL':<12}{'avg R':<8}{'hit'}"
    )
    for b in d4["buckets"]:
        rng = f"{b['vol_ratio_range'][0]}–{b['vol_ratio_range'][1]}"
        print(
            f"  {b['bucket']:<10}{rng:<14}{b['days']:<6}{b['avg_size']:<6}{b['avg_edge_retained_pct']:<12}"
            f"{b['avg_portfolio_vol']:<10}{b['realized_pnl']:<12}{b['realized_avg_r']!s:<8}{b['realized_hit_rate']}"
        )

    summary = {"edge_by_size": d1, "lost_edge": d2, "frontier": d3, "regime": d4}
    out = out_dir / "shadow_diagnostics_summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nsummary → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
