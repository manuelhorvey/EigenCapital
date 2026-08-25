"""Campaign 6 — 1H Confirmation of ST-001 (Asia→London Transition Continuation).

EXTREMELY NARROW confirmation campaign. Not exploration.

Research question:
    Does the Asia→London continuation mechanism remain statistically
    significant, walk-forward stable, cost-resilient, and risk-manageable
    when expressed at 1H?

Pre-registered design:
- PRIMARY: ST-001 economic definition translated to 1H bars exactly once —
  overnight momentum over the final ~2h of the Asian session, expressed at
  the London open bar (UTC 07). Holding periods 1–4 bars (1h–4h).
- SENSITIVITY GRID (diagnostics only, never used for selection):
  London-open boundary b ∈ {06, 07, 08} × overnight lookback k ∈ {2, 3}.
  All variants are Bonferroni-corrected as one pre-registered family.
- Same frozen validation gates as Campaigns 4/5 (classify()).
- Same cost model (base 13bps / adverse 22bps).
- Same permutation methodology.
- Data: ~8 years of real Exness MT5 H1 bars (2018 → 2026).

Confirmation rule (fail-closed):
    CONFIRMED iff the PRIMARY configuration reaches Verdict.SUPPORTED at some
    horizon AND its permutation p survives Bonferroni correction across the
    4 horizons (p_adj ≤ 0.05). Otherwise NOT_CONFIRMED. A NOT_CONFIRMED result
    leaves ST-001 as a 30M-supported research candidate, not production alpha.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from eigencapital.research.intraday.campaign4_15m import (
    SESSION_BOUNDS_UTC,
    UNIVERSE,
    CostModel,
)
from eigencapital.research.intraday.campaign5_30m import classify

# ── Constants ───────────────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR = 252
BARS_PER_TRADING_DAY = 24          # H1 bars
HORIZONS = [1, 2, 3, 4]            # hours
PRIMARY_BOUNDARY = 7               # London open UTC hour (C4/C5 convention)
PRIMARY_LOOKBACK = 2               # ~2h overnight momentum (economic match to C5)

BOUNDARY_GRID = [6, 7, 8]
LOOKBACK_GRID = [2, 3]

DATA_DIR = "data/intraday_h1"
REPORT_JSON = "reports/campaign6_1h_confirmation.json"
REPORT_MD = "reports/campaign6_1h_confirmation.md"


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL: same economic mechanism, expressed once per (boundary, lookback)
# ═══════════════════════════════════════════════════════════════════════

def make_asia_london_signal(boundary_hour: int, lookback: int) -> Callable:
    """Asia→London continuation at 1H.

    Signal = return over the last `lookback` hours of the Asian session,
    gated to the single London-open bar (UTC boundary_hour). Uses only
    information available at signal time (no look-ahead by construction:
    momentum is backward-looking; gate is calendar time).
    """

    def sig(df: pd.DataFrame, **kw) -> pd.Series:
        if "time" not in df.columns:
            return pd.Series(0.0, index=df.index)
        mom = df["close"].pct_change(lookback)
        hours = pd.to_datetime(df["time"]).dt.hour
        mask = (hours == boundary_hour).astype(float)
        return mom * mask

    return sig


PRIMARY_SIGNAL = make_asia_london_signal(PRIMARY_BOUNDARY, PRIMARY_LOOKBACK)


# ═══════════════════════════════════════════════════════════════════════
# ENGINE (1H-correct annualization) — identical methodology to C4/C5
# ═══════════════════════════════════════════════════════════════════════

def bt(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
    cost: float,
) -> Tuple[float, float, float, int]:
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["close"].pct_change(hp).shift(-hp)
    strat = pos * fwd
    n_trades = int(pos.diff().abs().sum())
    clean = strat.dropna()
    if len(clean) < 30 or clean.std() == 0:
        return 0.0, 0.0, 0.0, n_trades
    bars_per_year = TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp
    ann = np.sqrt(bars_per_year)
    sharpe = float(clean.mean() / clean.std() * ann)
    cum = (1 + clean).cumprod()
    dd = float(((cum - cum.cummax()) / cum.cummax()).min())
    net_ret = float(clean.sum()) - n_trades * cost
    return sharpe, net_ret, dd, n_trades


def _threshold(sig: pd.Series) -> pd.Series:
    thr = sig.rolling(10, min_periods=5).std() * 0.5
    return sig.where(sig.abs() > thr, 0)


def wf_validate(
    df: pd.DataFrame,
    func: Callable,
    hp: int,
    n_folds: int = 5,
) -> Tuple[float, float]:
    fold_size = len(df) // (n_folds + 1)
    fold_sharpes: List[float] = []
    for i in range(n_folds):
        s = fold_size * (i + 1)
        e = min(s + fold_size, len(df))
        if e - s < 50:
            continue
        try:
            sig = _threshold(func(df.iloc[s:e]).fillna(0))
            sharpe, _, _, _ = bt(df.iloc[s:e], sig, hp, CostModel.BASE)
            fold_sharpes.append(sharpe)
        except Exception:
            fold_sharpes.append(0.0)
    if not fold_sharpes:
        return 0.0, 0.0
    consistency = sum(1 for s in fold_sharpes if s > 0) / len(fold_sharpes)
    return consistency, float(np.mean(fold_sharpes))


def permutation_test(
    df: pd.DataFrame,
    func: Callable,
    hp: int,
    n_permutations: int = 200,
) -> float:
    try:
        real_sig = _threshold(func(df).fillna(0))
        real_sharpe, _, _, _ = bt(df, real_sig, hp, CostModel.BASE)
    except Exception:
        return 1.0
    if real_sharpe <= 0:
        return 1.0
    count_ge = 0
    for _ in range(n_permutations):
        shuffled = pd.Series(
            real_sig.sample(frac=1.0, replace=False).values, index=df.index
        )
        perm_sharpe, _, _, _ = bt(df, shuffled, hp, CostModel.BASE)
        if perm_sharpe >= real_sharpe:
            count_ge += 1
    return count_ge / n_permutations


def regime_analysis(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Year and session decomposition of strategy returns."""
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["close"].pct_change(hp).shift(-hp)
    strat = (pos * fwd).dropna()
    ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp)

    year_sharpes: Dict[str, float] = {}
    session_sharpes: Dict[str, float] = {}
    year_dd: Dict[str, float] = {}
    if "time" not in df.columns:
        return year_sharpes, session_sharpes, year_dd

    years = pd.to_datetime(df.loc[strat.index, "time"]).dt.year
    for yr, grp in strat.groupby(years):
        if len(grp) < 30 or grp.std() == 0:
            continue
        year_sharpes[str(yr)] = float(grp.mean() / grp.std() * ann)
        cum = (1 + grp).cumprod()
        year_dd[str(yr)] = float(((cum - cum.cummax()) / cum.cummax()).min())

    hours = pd.to_datetime(df.loc[strat.index, "time"]).dt.hour
    for sess_name, (lo, hi) in SESSION_BOUNDS_UTC.items():
        sess_ret = strat[(hours >= lo) & (hours < hi)]
        if len(sess_ret) < 30 or sess_ret.std() == 0:
            continue
        session_sharpes[sess_name] = float(sess_ret.mean() / sess_ret.std() * ann)

    return year_sharpes, session_sharpes, year_dd


def daily_returns(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
) -> pd.Series:
    """Strategy returns aggregated to daily frequency (for correlation/concentration)."""
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["close"].pct_change(hp).shift(-hp)
    strat = (pos * fwd).dropna()
    if "time" not in df.columns or strat.empty:
        return strat
    dates = pd.to_datetime(df.loc[strat.index, "time"]).dt.date
    daily = strat.groupby(dates.values).sum()
    daily.index = pd.to_datetime(daily.index)
    return daily


# ═══════════════════════════════════════════════════════════════════════
# RESULT CONTAINER
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ConfirmResult:
    variant: str                 # e.g. "primary(b=07,k=2)"
    boundary: int
    lookback: int
    hp: int
    gross_sharpe: float = 0.0
    net_base: float = 0.0
    net_adverse: float = 0.0
    max_dd: float = 0.0
    trades: int = 0
    wf_consistency: float = 0.0
    wf_oos_sharpe: float = 0.0
    degradation: float = 0.0
    permutation_p: float = 1.0
    permutation_p_bonferroni: float = 1.0
    verdict: str = "not_evaluated"
    reasons: List[str] = field(default_factory=list)
    sym_sharpes: Dict[str, float] = field(default_factory=dict)
    sym_pnl_share: Dict[str, float] = field(default_factory=dict)
    year_sharpes: Dict[str, float] = field(default_factory=dict)
    year_dd: Dict[str, float] = field(default_factory=dict)
    session_sharpes: Dict[str, float] = field(default_factory=dict)
    primary_failure: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d.update({
            k: {kk: round(vv, 4) for kk, vv in v.items()}
            for k, v in d.items()
            if isinstance(v, dict)
        })
        for k in ["gross_sharpe", "net_base", "net_adverse", "max_dd",
                  "wf_consistency", "wf_oos_sharpe", "degradation",
                  "permutation_p", "permutation_p_bonferroni"]:
            d[k] = round(d[k], 4)
        return d


# ═══════════════════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════════════════

def evaluate_variant(
    func: Callable,
    hp: int,
    data: Dict[str, pd.DataFrame],
    variant_name: str,
    boundary: int,
    lookback: int,
    bonferroni_factor: int,
    n_perms: int = 100,
) -> ConfirmResult:
    gross_vals, net_vals, adv_vals, dd_vals = [], [], [], []
    total_trades = 0
    sym_net: Dict[str, float] = {}
    daily_by_sym: Dict[str, pd.Series] = {}

    for s, df in data.items():
        try:
            sig_raw = func(df).fillna(0)
            sig = _threshold(sig_raw)
            g, _, _, t = bt(df, sig, hp, 0)
            nb, _, _, _ = bt(df, sig, hp, CostModel.BASE)
            na, _, dd, _ = bt(df, sig, hp, CostModel.ADVERSE)
            gross_vals.append(g)
            net_vals.append(nb)
            adv_vals.append(na)
            dd_vals.append(dd)
            total_trades += t
            sym_net[s] = nb
            daily_by_sym[s] = daily_returns(df, sig_raw, hp)
        except Exception:
            continue

    ag = float(np.mean(gross_vals)) if gross_vals else 0.0
    anb = float(np.mean(net_vals)) if net_vals else 0.0
    ana = float(np.mean(adv_vals)) if adv_vals else 0.0
    mdd = float(min(dd_vals)) if dd_vals else 0.0

    anchor = data.get("EURUSDm", list(data.values())[0])
    wf_cons, wf_oos = wf_validate(anchor, func, hp)
    deg = 1 - (anb / ag) if abs(ag) > 1e-3 else 1.0

    # Permutation on anchor instrument (same methodology as C4/C5)
    perm_p = permutation_test(anchor, func, hp, n_permutations=n_perms)
    p_adj = min(1.0, perm_p * bonferroni_factor)

    # Regime decomposition on anchor
    try:
        yr_sh, sess_sh, yr_dd = regime_analysis(anchor, _threshold(func(anchor).fillna(0)), hp)
    except Exception:
        yr_sh, sess_sh, yr_dd = {}, {}, {}

    # PnL concentration across instruments (share of positive daily PnL mass)
    pnl_share: Dict[str, float] = {}
    try:
        total_pos = sum(max(0.0, float(v.sum())) for v in daily_by_sym.values())
        if total_pos > 0:
            pnl_share = {
                s: round(max(0.0, float(r.sum())) / total_pos, 4)
                for s, r in daily_by_sym.items()
            }
    except Exception:
        pass

    # Classify using FROZEN C4/C5 gates
    from eigencapital.research.intraday.campaign4_15m import HypResult, Verdict

    hr = HypResult(
        hid=variant_name, family="asia_london_confirm",
        description=f"ST-001 @1H ({variant_name})", hp=hp,
        gross_sharpe=ag, net_base=anb, net_adverse=ana, max_dd=mdd,
        trades=total_trades, wf_consistency=wf_cons, wf_oos_sharpe=wf_oos,
        degradation=deg, permutation_p=p_adj,
        sym_sharpes=sym_net,
    )
    verdict_v, reasons, primary_fail = classify(hr)

    return ConfirmResult(
        variant=variant_name, boundary=boundary, lookback=lookback, hp=hp,
        gross_sharpe=ag, net_base=anb, net_adverse=ana, max_dd=mdd,
        trades=total_trades, wf_consistency=wf_cons, wf_oos_sharpe=wf_oos,
        degradation=deg, permutation_p=perm_p,
        permutation_p_bonferroni=p_adj,
        verdict=verdict_v.value if hasattr(verdict_v, "value") else str(verdict_v),
        reasons=reasons, sym_sharpes=sym_net, sym_pnl_share=pnl_share,
        year_sharpes=yr_sh, year_dd=yr_dd, session_sharpes=sess_sh,
        primary_failure=primary_fail,
    )


def cross_instrument_correlation(
    data: Dict[str, pd.DataFrame],
    func: Callable,
    hp: int,
) -> Dict[Tuple[str, str], float]:
    """Average pairwise correlation of daily strategy returns across instruments."""
    daily: Dict[str, pd.Series] = {}
    for s, df in data.items():
        try:
            daily[s] = daily_returns(df, _threshold(func(df).fillna(0)), hp)
        except Exception:
            continue
    corrs: Dict[Tuple[str, str], float] = {}
    syms = sorted(daily)
    for a, b in itertools.combinations(syms, 2):
        joined = pd.concat([daily[a].rename(a), daily[b].rename(b)], axis=1).dropna()
        if len(joined) > 60:
            corrs[(a, b)] = round(float(joined[a].corr(joined[b])), 4)
    return corrs


# ═══════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════

def run(data_dir: str = DATA_DIR) -> Tuple[List[ConfirmResult], List[ConfirmResult]]:
    data: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(data_dir, f"{s}_H1.csv")
        if os.path.exists(p):
            data[s] = pd.read_csv(p, parse_dates=["time"])
            print(f"  Loaded {s}: {len(data[s])} bars "
                  f"({data[s]['time'].iloc[0]} → {data[s]['time'].iloc[-1]})")
    if not data:
        print("ERROR: No H1 data found")
        return [], []

    # Family size for Bonferroni: 4 horizons × sensitivity grid
    grid_size = len(BOUNDARY_GRID) * len(LOOKBACK_GRID)
    family_size = len(HORIZONS) * grid_size

    print(f"\nFamily size for Bonferroni: {family_size} "
          f"(4 horizons x {grid_size} variants)")

    results: List[ConfirmResult] = []
    print("\n=== PRIMARY: ST-001 @1H (b=07, k=2) ===")
    for hp in HORIZONS:
        r = evaluate_variant(
            PRIMARY_SIGNAL, hp, data, f"b={PRIMARY_BOUNDARY:02d},k={PRIMARY_LOOKBACK}",
            PRIMARY_BOUNDARY, PRIMARY_LOOKBACK,
            bonferroni_factor=family_size, n_perms=200,
        )
        print(f"  HP={hp}h: gross={r.gross_sharpe:+.3f} net={r.net_base:+.3f} "
              f"adv={r.net_adverse:+.3f} DD={r.max_dd:.2f} WF={r.wf_consistency:.0%} "
              f"perm_p={r.permutation_p:.3f} p_adj={r.permutation_p_bonferroni:.3f} "
              f"→ {r.verdict}")
        results.append(r)

    sensitivity: List[ConfirmResult] = []
    print("\n=== SENSITIVITY GRID (diagnostics only) ===")
    for b, k in itertools.product(BOUNDARY_GRID, LOOKBACK_GRID):
        if b == PRIMARY_BOUNDARY and k == PRIMARY_LOOKBACK:
            continue
        for hp in HORIZONS:
            r = evaluate_variant(
                make_asia_london_signal(b, k), hp, data,
                f"b={b:02d},k={k}", b, k,
                bonferroni_factor=family_size, n_perms=100,
            )
            print(f"  b={b:02d} k={k} HP={hp}h: net={r.net_base:+.3f} "
                  f"WF={r.wf_consistency:.0%} p_adj={r.permutation_p_bonferroni:.3f} "
                  f"→ {r.verdict}")
            sensitivity.append(r)

    return results, sensitivity


def confirm_verdict(results: List[ConfirmResult]) -> Tuple[str, List[str]]:
    """Fail-closed confirmation decision."""
    notes: List[str] = []
    confirmed = [
        r for r in results
        if r.verdict == "supported" and r.permutation_p_bonferroni <= 0.05
    ]
    if confirmed:
        best = max(confirmed, key=lambda r: r.net_base)
        notes.append(
            f"CONFIRMED at HP={best.hp}h (net={best.net_base:+.3f}, "
            f"p_adj={best.permutation_p_bonferroni:.3f})"
        )
        return "CONFIRMED", notes

    any_supported = [r for r in results if r.verdict == "supported"]
    if any_supported:
        notes.append(
            "Gate-passing horizon(s) exist but fail Bonferroni family-wise "
            "correction — treated as NOT CONFIRMED (fail-closed)."
        )
    else:
        notes.append("No horizon passes all frozen gates at 1H.")
    return "NOT_CONFIRMED", notes


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════

def write_reports(
    results: List[ConfirmResult],
    sensitivity: List[ConfirmResult],
    correlations: Optional[Dict[Tuple[str, str], float]] = None,
) -> None:
    now = time.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs("reports", exist_ok=True)
    final_verdict, notes = confirm_verdict(results)

    lines: List[str] = [
        "# CAMPAIGN 6 — 1H CONFIRMATION OF ST-001",
        "",
        "**Mechanism:** Asia→London transition continuation (ST-001)",
        "**Universe:** 8 instruments (Exness MT5, H1)",
        "**Data:** ~50,000 bars/symbol (~8 years, 2018 → 2026)",
        f"**Generated:** {now}",
        f"**Costs:** base {CostModel.BASE*10000:.0f}bps / adverse {CostModel.ADVERSE*10000:.0f}bps",
        f"**Multiple testing:** Bonferroni over {len(results)} primary + "
        f"{len(sensitivity)} sensitivity evaluations",
        "",
        "---", "",
        f"## CONFIRMATION VERDICT: **{final_verdict}**", "",
    ]
    lines.extend(f"- {n}" for n in notes)
    lines.extend(["", "---", "", "## PRIMARY RESULTS (b=07, k=2)", "",
                  "| HP | Gross | Net | Adverse | MaxDD | WF | OOS | Perm p | p_adj | Verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|"])
    for r in results:
        lines.append(
            f"| {r.hp}h | {r.gross_sharpe:+.3f} | {r.net_base:+.3f} | "
            f"{r.net_adverse:+.3f} | {r.max_dd:.2f} | {r.wf_consistency:.0%} | "
            f"{r.wf_oos_sharpe:+.3f} | {r.permutation_p:.3f} | "
            f"{r.permutation_p_bonferroni:.3f} | {r.verdict} |"
        )

    best_primary = max(results, key=lambda r: r.net_base)
    lines.extend([
        "", f"### Best-primary deep dive (HP={best_primary.hp}h)", "",
        "**Year-by-year:**",
        *[f"- {yr}: Sharpe {sh:+.2f}, DD {dd:.1%}"
          for (yr, sh), (_, dd) in zip(sorted(best_primary.year_sharpes.items()),
                                       sorted(best_primary.year_dd.items(),
                                              key=lambda x: x[0]))],
        "",
        "**Session attribution:**",
        *[f"- {s}: {sh:+.2f}" for s, sh in sorted(best_primary.session_sharpes.items())],
        "",
        "**Per-instrument (net Sharpe | PnL share):**",
        *[f"- {s}: {best_primary.sym_sharpes.get(s, 0):+.3f} | "
          f"{best_primary.sym_pnl_share.get(s, 0):.1%}"
          for s in sorted(best_primary.sym_sharpes)],
        "",
    ])

    if correlations:
        vals = sorted(correlations.values())
        avg = float(np.mean(vals)) if vals else 0.0
        mx = max(vals) if vals else 0.0
        lines.extend([
            "### Cross-instrument concentration", "",
            f"- Average pairwise correlation of daily strategy returns: {avg:+.3f}",
            f"- Maximum pairwise correlation: {mx:+.3f}",
            "- Interpretation: high correlation ⇒ concentrated risk factor, "
            "not independent edges.", "",
        ])

    lines.extend([
        "---", "",
        "## SENSITIVITY GRID (diagnostics only — no selection)", "",
        "| Boundary | Lookback | HP | Net | WF | p_adj | Verdict |",
        "|---|---|---|---|---|---|---|",
    ])
    for r in sensitivity:
        lines.append(
            f"| {r.boundary:02d}:00 | {r.lookback}h | {r.hp}h | "
            f"{r.net_base:+.3f} | {r.wf_consistency:.0%} | "
            f"{r.permutation_p_bonferroni:.3f} | {r.verdict} |"
        )
    robust_count = sum(1 for r in sensitivity
                       if r.net_base > 0 and r.permutation_p_bonferroni <= 0.10)
    lines.extend([
        "",
        f"Sensitivity robustness: {robust_count}/{len(sensitivity)} variants "
        "positive with p_adj ≤ 0.10. Robustness across neighbouring boundaries/"
        "lookbacks indicates a stable economic effect rather than a knife-edge fit.",
        "",
        "---", "",
        "## DECISION", "",
    ])
    if final_verdict == "CONFIRMED":
        lines.append(
            "Cross-timeframe evidence obtained. Next step per program rules: "
            "dedicated intraday RISK TRANSFORMATION campaign (drawdown control, "
            "position sizing, portfolio expression) — NOT direct deployment."
        )
    else:
        lines.append(
            "ST-001 remains a 30M-supported RESEARCH candidate. It must NOT be "
            "promoted toward the fidelity ladder without independent confirmation."
        )

    md = "\n".join(lines) + "\n"
    with open(REPORT_MD, "w") as f:
        f.write(md)

    payload = {
        "campaign": "campaign6_1h_confirmation",
        "mechanism": "ST-001 asia->london transition continuation",
        "final_verdict": final_verdict,
        "notes": notes,
        "generated": now,
        "bonferroni_family_size": len(results) + len(sensitivity),
        "primary": [r.to_dict() for r in results],
        "sensitivity": [r.to_dict() for r in sensitivity],
        "cross_instrument_correlation": (
            {f"{a}|{b}": c for (a, b), c in correlations.items()}
            if correlations else {}
        ),
    }
    with open(REPORT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\nReports written: {REPORT_MD}, {REPORT_JSON}")
    print(f"\nFINAL CONFIRMATION VERDICT: {final_verdict}")
    for n in notes:
        print(f"  - {n}")


if __name__ == "__main__":
    import sys
    ddir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    res, sens = run(ddir)

    # Cross-instrument correlation at primary config, best-net horizon
    data_tmp: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(ddir, f"{s}_H1.csv")
        if os.path.exists(p):
            data_tmp[s] = pd.read_csv(p, parse_dates=["time"])
    best_hp = max(res, key=lambda r: r.net_base).hp if res else 2
    corrs = cross_instrument_correlation(data_tmp, PRIMARY_SIGNAL, best_hp)

    write_reports(res, sens, corrs)
