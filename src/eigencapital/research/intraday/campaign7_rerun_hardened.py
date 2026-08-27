"""Campaign 7 RERUN — Hardened Governance over the immutable tick snapshot.

WHY: Campaign 7 discovered TF-003 with raw permutation p=0.03, but the
campaign ran an 18-hypothesis × 4-horizon family WITHOUT family-wise
correction, and its Sharpe accounting charged costs outside the return
series. Both are research-engine defects. This rerun fixes the measurement
system and re-decides every C7 verdict. No hypothesis is modified; no
parameter is tuned.

HARDENING APPLIED (pre-registered here, before results):
  1. Corrected per-bar cost engine (Stage A of C8, locked by unit tests):
     costs charged at EVERY position flip inside the return series.
     One-way base 6.5 bps / adverse 11 bps.
  2. Family-wise correction within C7:
     p_adj_family = min(1, p_raw × 72)   [18 hypotheses × 4 horizons]
     SUPPORTED requires p_adj_family ≤ 0.05.
   3. Cumulative trial ledger across the whole intraday program:
      prior evaluations = 133 (C1–C6) + 72 (this family) = 205.
      p_adj_cumulative = min(1, p_raw × 205), reported for transparency.
      If a hypothesis passes the family gate but cumulative-adj > 0.05,
      it is downgraded to FRAGILE with reason 'cumulative_trial_weakness'.
      Threshold note: family pass implies p_raw <= 0.05/72, so the maximum
      reachable cumulative-adj among family survivors is
      205 × 0.05/72 ≈ 0.1424; any threshold above that is dead code.
  4. Verdicts via the frozen classify() gates fed with CORRECTED net values.

DECISION RULE (fail-closed):
  - any SUPPORTED survivor → proceeds to C8 confirmation on fresh data
  - zero survivors → microstructure branch FROZEN like M1–1H
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Dict, List

import numpy as np
import pandas as pd

from eigencapital.research.intraday.campaign4_15m import (
    UNIVERSE,
    HypResult,
    Verdict,
)
from eigencapital.research.intraday.campaign5_30m import classify
from eigencapital.research.intraday.campaign7_micro import (
    DATA_DIR,
    HORIZONS,
    HYPOTHESES,
    SIGNALS,
    _threshold,
)
from eigencapital.research.intraday.campaign8_tf003_confirmation import (
    COST_ONE_WAY_ADVERSE,
    COST_ONE_WAY_BASE,
    bt_corrected,
    permutation_test_corrected,
    wf_validate_corrected,
)

# ── Governance constants ────────────────────────────────────────────────

PRIOR_EVALUATIONS = 133  # C1(24) + C2(20) + C3(16) + C4(31) + C5(18) + C6(24)
FAMILY_SIZE = len(HYPOTHESES) * len(HORIZONS)  # 18 × 4 = 72
CUMULATIVE_TRIALS = PRIOR_EVALUATIONS + FAMILY_SIZE  # 205

FAMILY_P_MAX = 0.05  # SUPPORTED gate on family-corrected p
# SUPPORTED additionally requires cumulative-adjusted p <= 0.05. A larger
# threshold would be unreachable: family pass caps p_raw at 0.05/72, so
# max possible cumulative-adj among survivors is 205*0.05/72 ≈ 0.1424.
CUMULATIVE_DOWNGRADE = 0.05  # downgrade threshold on cumulative-adj p

REPORT_JSON = "reports/campaign7_rerun_hardened.json"
REPORT_MD = "reports/campaign7_rerun_hardened.md"


def family_adjust(p_raw: float) -> float:
    return min(1.0, p_raw * FAMILY_SIZE)


def cumulative_adjust(p_raw: float) -> float:
    return min(1.0, p_raw * CUMULATIVE_TRIALS)


# ═══════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════


def run(data_dir: str = DATA_DIR) -> List[HypResult]:
    data: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(data_dir, f"{s}_M5micro.csv")
        if os.path.exists(p):
            data[s] = pd.read_csv(p, parse_dates=["time"])
    if not data:
        print("ERROR: no microstructure bars")
        return []
    print(f"Loaded {len(data)} symbols from snapshot (family={FAMILY_SIZE}, cumulative={CUMULATIVE_TRIALS})")

    anchor_name = next((s for s in ["EURUSDm", "XAUUSDm"] if s in data), list(data)[0])
    anchor = data[anchor_name]

    results: List[HypResult] = []
    eval_count = 0

    for h in HYPOTHESES:
        func = SIGNALS[h.signal]
        is_ll = h.family == "lead_lag"
        best, best_score = None, -999

        for hp in HORIZONS:
            gross_vals, net_vals, adv_vals, dd_vals = [], [], [], []
            total_flips = 0
            sym_net: Dict[str, float] = {}

            for s, df in data.items():
                try:
                    kw = {"all_data": data} if is_ll else {}
                    sig = _threshold(func(df, **kw))
                    r_b = bt_corrected(df, sig, hp, COST_ONE_WAY_BASE)
                    r_a = bt_corrected(df, sig, hp, COST_ONE_WAY_ADVERSE)
                    gross_vals.append(r_b.gross_sharpe)
                    net_vals.append(r_b.net_sharpe)
                    adv_vals.append(r_a.net_sharpe)
                    dd_vals.append(r_b.max_dd)
                    total_flips += r_b.n_flips
                    sym_net[s] = r_b.net_sharpe
                except Exception:
                    continue
            if not gross_vals:
                continue
            eval_count += 1

            ag = float(np.mean(gross_vals))
            anb = float(np.mean(net_vals))
            ana = float(np.mean(adv_vals))
            mdd = float(min(dd_vals))

            kw_anchor = {"all_data": data} if is_ll else {}
            wf_cons, wf_oos = wf_validate_corrected(
                anchor,
                lambda d, f=func, k=kw_anchor: f(d, **k),
                hp,
                COST_ONE_WAY_BASE,
            )
            perm_p_raw = permutation_test_corrected(
                anchor,
                lambda d, f=func, k=kw_anchor: f(d, **k),
                hp,
                COST_ONE_WAY_BASE,
                n_permutations=100,
            )
            deg = 1 - anb / ag if abs(ag) > 1e-3 else 1.0

            # Frozen gates fed with family-corrected p
            hr = HypResult(
                hid=h.hid,
                family=h.family,
                description=h.description,
                hp=hp,
                gross_sharpe=ag,
                net_base=anb,
                net_adverse=ana,
                max_dd=mdd,
                trades=total_flips,
                wf_consistency=wf_cons,
                wf_oos_sharpe=wf_oos,
                degradation=deg,
                permutation_p=family_adjust(perm_p_raw),
                sym_sharpes=sym_net,
            )
            verdict_v, reasons, primary_fail = classify(hr)

            p_cum = cumulative_adjust(perm_p_raw)

            # Cumulative-trial downgrade: passed family gate but the whole-
            # program ledger makes the evidence weak → never SUPPORTED.
            if verdict_v == Verdict.SUPPORTED and p_cum > CUMULATIVE_DOWNGRADE:
                verdict_v = Verdict.FRAGILE
                reasons.append("cumulative_trial_weakness")
                primary_fail = primary_fail or "cumulative_trial_weakness"

            r = hr
            r.verdict = verdict_v
            r.reasons = reasons
            r.primary_failure = primary_fail or ""
            r.permutation_p = perm_p_raw  # store RAW p in artifact;
            # adjusted values recorded below in extra fields
            object.__setattr__(
                r,
                "_governance",
                {
                    "p_raw": round(perm_p_raw, 4),
                    "p_adj_family": round(family_adjust(perm_p_raw), 4),
                    "p_adj_cumulative": round(p_cum, 4),
                    "cost_model": "corrected_one_way",
                    "eval_count": eval_count,
                },
            )

            print(
                f"  {h.hid} HP={hp} ({hp * 5:>2}m): gross={ag:+.2f} "
                f"net={anb:+.2f} adv={ana:+.2f} DD={mdd:.1%} "
                f"WF={wf_cons:.0%} p_raw={perm_p_raw:.3f} "
                f"p_fam={family_adjust(perm_p_raw):.3f} → {verdict_v.value}"
            )

            score = anb + wf_cons * 0.5 - family_adjust(perm_p_raw) * 0.2
            if score > best_score:
                best_score, best = score, r

        results.append(
            best
            if best
            else HypResult(
                hid=h.hid,
                family=h.family,
                description=h.description,
                hp=HORIZONS[0],
                verdict=Verdict.REJECTED,
                reasons=["no_data"],
                primary_failure="no_data",
            )
        )

    print(f"\nEvaluated {eval_count}/{FAMILY_SIZE} combinations")
    return results


def to_dict_with_governance(r: HypResult) -> dict:
    d = r.to_dict()
    gov = getattr(r, "_governance", None)
    if gov:
        d["governance"] = gov
    return d


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════


def write_reports(results: List[HypResult]) -> str:
    now = time.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs("reports", exist_ok=True)
    surv = [r for r in results if r.verdict == Verdict.SUPPORTED]

    lines = [
        "# CAMPAIGN 7 RERUN — HARDENED GOVERNANCE",
        "",
        "**Snapshot:** immutable C7 tick snapshot (unchanged)",
        f"**Generated:** {now}",
        "**Engine:** corrected per-bar cost accounting (one-way 6.5/11 bps)",
        f"**Family:** {FAMILY_SIZE} evaluations (18 hyp × 4 horizons); Bonferroni within-family",
        f"**Cumulative ledger:** {CUMULATIVE_TRIALS} program evaluations",
        "",
        "---",
        "",
        "## VERDICT DISTRIBUTION (hardened)",
        "",
        "| Verdict | Count | IDs |",
        "|---|---|---|",
    ]
    for v in [
        "rejected",
        "regime_dependent",
        "cost_sensitive",
        "fragile",
        "inconclusive",
        "supported",
    ]:
        hs = [r for r in results if r.verdict.value == v]
        if hs:
            lines.append(f"| **{v.upper()}** | {len(hs)} | {', '.join(x.hid for x in hs)} |")

    top = sorted(results, key=lambda r: r.net_base, reverse=True)[:6]
    lines += [
        "",
        "## TOP RESULTS UNDER HARDENED ACCOUNTING",
        "",
        "| ID | HP | Gross | Net | Adv | DD | WF | p_raw | p_fam | p_cum | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in top:
        gov = getattr(r, "_governance", {})
        lines.append(
            f"| {r.hid} | {r.hp * 5}m | {r.gross_sharpe:+.2f} | "
            f"{r.net_base:+.2f} | {r.net_adverse:+.2f} | {r.max_dd:.1%} | "
            f"{r.wf_consistency:.0%} | {gov.get('p_raw', 1):.3f} | "
            f"{gov.get('p_adj_family', 1):.3f} | "
            f"{gov.get('p_adj_cumulative', 1):.3f} | {r.verdict.value} |"
        )

    tf003 = next((r for r in results if r.hid == "TF-003"), None)
    lines += ["", "## TF-003 DISPOSITION UNDER HARDENED GOVERNANCE", ""]
    if tf003 is not None:
        gov = getattr(tf003, "_governance", {})
        lines += [
            f"- Corrected net Sharpe (base): **{tf003.net_base:+.2f}** (adverse {tf003.net_adverse:+.2f})",
            f"- Max DD (net): {tf003.max_dd:.1%}",
            f"- WF consistency: {tf003.wf_consistency:.0%}",
            f"- p_raw {gov.get('p_raw', 1):.3f} → p_family "
            f"{gov.get('p_adj_family', 1):.3f} → p_cumulative "
            f"{gov.get('p_adj_cumulative', 1):.3f}",
            f"- Final verdict: **{tf003.verdict.value.upper()}** (reasons: {', '.join(tf003.reasons) or 'none'})",
        ]

    lines += ["", "## DECISION", ""]
    if surv:
        ids = ", ".join(r.hid for r in surv)
        lines += [
            f"SUPPORTED under hardened governance: **{ids}**.",
            "Proceed to C8 confirmation on fresh/held-out tick data with cumulative trial accounting inherited.",
        ]
    else:
        lines += [
            "**ZERO survivors under hardened governance.",
            "The broker-microstructure branch is FROZEN**, consistent with "
            "the M1–1H OHLCV freeze. The measurement-system defects that "
            "motivated this rerun remain fixed for all future campaigns.",
        ]

    md = "\n".join(lines) + "\n"
    with open(REPORT_MD, "w") as f:
        f.write(md)
    with open(REPORT_JSON, "w") as f:
        json.dump([to_dict_with_governance(r) for r in results], f, indent=2)
    print(f"\nReports written: {REPORT_MD}, {REPORT_JSON}")
    return md


if __name__ == "__main__":
    import sys

    res = run(sys.argv[1] if len(sys.argv) > 1 else DATA_DIR)
    write_reports(res)
    dist = Counter(r.verdict.value for r in res)
    print("\nFINAL VERDICT DISTRIBUTION:", dict(dist))
