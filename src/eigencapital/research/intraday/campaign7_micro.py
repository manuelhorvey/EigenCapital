"""Campaign 7 — Broker-Specific Microstructure (Real Tick Quotes).

NEW INFORMATION SOURCE campaign. The OHLCV timeframe branch (M1→1H) is FROZEN
(see docs/research/INTRADAY_TIMEFRAME_BRANCH_FROZEN.md).

INFORMATION SOURCE LABEL (authoritative):
    This is BROKER-SPECIFIC MICROSTRUCTURE derived from Exness MT5 quote
    ticks (bid/ask/ms). It is NOT centralized institutional order flow.
    Any conclusion applies to this broker's quote stream only.

Data: real quote ticks aggregated into M5 microstructure bars:
    n_ticks, up_frac, dn_frac, signed_flow,
    spread_mean_bps, spread_max_bps, mid OHLC, mid_ret.

Pre-registered hypothesis families (~18):
  A. Quote-flow imbalance (TF-001..003)
  B. Tick arrival intensity (AI-001..003)
  C. Spread dynamics / liquidity (SD-001..003)
  D. Price impact per tick (PI-001..002)
  E. Directional persistence (PE-001..002)
  F. Cross-instrument lead/lag (LL-001..003)
  G. Composites (CO-001..002)

Validation pipeline identical to Campaigns 4–6: frozen gates (classify),
chronological walk-forward, permutation significance, base/adverse costs.
No tuning after results.

Multiple-testing control (pre-registered):
    Every hypothesis × horizon evaluation in this campaign forms ONE
    Bonferroni family. A verdict may only reach SUPPORTED if the raw
    permutation p survives correction across the full family size
    (p_adj = min(1, p * n_evals) ≤ 0.05). Raw and adjusted p are both
    reported; classification re-runs on the adjusted p.

Cumulative trial accounting:
    This campaign's evaluations join the frozen intraday search history
    (Campaigns 1–6, see PRIOR_EVALUATIONS_BY_CAMPAIGN below) so any
    future deflated-Sharpe computation carries the true N, not N=18.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from eigencapital.research.intraday.campaign4_15m import (
    SESSION_BOUNDS_UTC,
    UNIVERSE,
    CostModel,
    Hypothesis,
    HypResult,
    Verdict,
    _rmean,
    _rstd,
    _safe_div,
)
from eigencapital.research.intraday.campaign5_30m import classify

# ── Constants ───────────────────────────────────────────────────────────

HORIZONS = [1, 2, 3, 6]  # M5 bars: 5m / 10m / 15m / 30m
TRADING_DAYS_PER_YEAR = 252
BARS_PER_TRADING_DAY = 288  # 24h market / 5min

DATA_DIR = "data/tick_micro_m5"
REPORT_JSON = "reports/campaign7_micro_map.json"
REPORT_MD = "reports/campaign7_micro_map.md"

# Cumulative trial accounting — evaluation counts from the frozen intraday
# timeframe branch (rows of the scoreboard in
# docs/research/INTRADAY_TIMEFRAME_BRANCH_FROZEN.md). Any survivor here must
# be deflated against N = prior + current, never against this campaign alone.
PRIOR_EVALUATIONS_BY_CAMPAIGN = {
    "c1_m5_price_based": 24,
    "c2_m5_microstructure_proxy": 20,
    "c3_m1_orderflow_liquidity": 16,
    "c4_m15_multi_family": 31,
    "c5_m30_mechanism": 18,
    "c6_h1_confirmation": 24,
}
PRIOR_EVALUATIONS = sum(PRIOR_EVALUATIONS_BY_CAMPAIGN.values())


@dataclass
class MicroHypResult(HypResult):
    """HypResult with family-wise corrected permutation p (Campaign 7)."""

    permutation_p_bonferroni: float = 1.0
    bonferroni_family_size: int = 0

    def to_dict(self) -> Dict[str, object]:
        d = super().to_dict()
        d["permutation_p_bonferroni"] = round(self.permutation_p_bonferroni, 4)
        d["bonferroni_family_size"] = self.bonferroni_family_size
        return d


# ═══════════════════════════════════════════════════════════════════════
# PRE-REGISTERED HYPOTHESES
# ═══════════════════════════════════════════════════════════════════════

HYPOTHESES: List[Hypothesis] = [
    # A. Quote-flow imbalance
    Hypothesis(
        "TF-001",
        "tick_flow",
        "Signed quote-flow continuation (1-bar)",
        "sig_flow_cont",
        "Uptick imbalance persists one bar",
    ),
    Hypothesis(
        "TF-002",
        "tick_flow",
        "Signed quote-flow continuation (3-bar)",
        "sig_flow_cont3",
        "Flow persistence over 15 minutes",
    ),
    Hypothesis(
        "TF-003",
        "tick_flow",
        "Flow-extreme reversal",
        "sig_flow_fade",
        "Extreme imbalance mean-reverts",
    ),
    # B. Arrival intensity
    Hypothesis(
        "AI-001",
        "intensity",
        "Tick-intensity anomaly + direction",
        "sig_intensity_dir",
        "Activity spikes accompany directional moves",
    ),
    Hypothesis(
        "AI-002",
        "intensity",
        "Intensity spike x flow composite",
        "sig_intensity_flow",
        "High-activity flows are informative",
    ),
    Hypothesis(
        "AI-003",
        "intensity",
        "Quiet-market reversion",
        "sig_quiet_rev",
        "Low intensity favors reversion",
    ),
    # C. Spread dynamics / liquidity
    Hypothesis(
        "SD-001",
        "spread",
        "Spread expansion reversal",
        "sig_spread_exp_rev",
        "Liquidity withdrawal precedes reversals",
    ),
    Hypothesis(
        "SD-002",
        "spread",
        "Spread contraction continuation",
        "sig_spread_contr_cont",
        "Healthy liquidity favors trends",
    ),
    Hypothesis(
        "SD-003",
        "spread",
        "Spread-spike fade",
        "sig_spread_spike_fade",
        "Transient spread spikes revert",
    ),
    # D. Price impact
    Hypothesis(
        "PI-001",
        "impact",
        "High impact-per-tick continuation",
        "sig_impact_cont",
        "Large moves per quote are informed",
    ),
    Hypothesis(
        "PI-002",
        "impact",
        "Low-impact move fade",
        "sig_low_impact_fade",
        "Drift without quotes is noise",
    ),
    # E. Persistence
    Hypothesis(
        "PE-001",
        "persistence",
        "Multi-bar directional persistence",
        "sig_bar_persist",
        "Consecutive directional M5 bars continue",
    ),
    Hypothesis(
        "PE-002",
        "persistence",
        "Quote-run persistence",
        "sig_quote_run",
        "Long same-direction quote runs continue",
    ),
    # F. Cross-instrument lead/lag (quote flow)
    Hypothesis(
        "LL-001",
        "lead_lag",
        "EURUSD flow leads GBPUSD (1-bar lag)",
        "sig_eur_gbp_flow",
        "Correlated majors share quote pressure",
    ),
    Hypothesis(
        "LL-002",
        "lead_lag",
        "US500 flow leads USTEC (1-bar lag)",
        "sig_sp500_nasdac_flow",
        "Index futures proxies share risk flow",
    ),
    Hypothesis(
        "LL-003",
        "lead_lag",
        "XAUUSD flow leads AUDUSD (1-bar lag)",
        "sig_gold_aud_flow",
        "Gold-linked commodity currency",
    ),
    # G. Composites (small, structurally motivated)
    Hypothesis(
        "CO-001",
        "composite",
        "Flow x spread-regime composite",
        "sig_flow_x_spread",
        "Flow signal conditioned on liquidity state",
    ),
    Hypothesis(
        "CO-002",
        "composite",
        "Intensity spike x micro-breakout",
        "sig_spike_breakout",
        "Confirmed micro-range breaks",
    ),
]

for h in HYPOTHESES:
    object.__setattr__(h, "phash", h.compute_hash())


# ═══════════════════════════════════════════════════════════════════════
# SIGNALS (operate on M5 microstructure feature columns; backward-looking)
# ═══════════════════════════════════════════════════════════════════════


def _z(s: pd.Series, n: int = 96) -> pd.Series:
    return _safe_div(s - _rmean(s, n), _rstd(s, n))


def sig_flow_cont(df: pd.DataFrame, **kw) -> pd.Series:
    return df["signed_flow"]


def sig_flow_cont3(df: pd.DataFrame, **kw) -> pd.Series:
    return df["signed_flow"].rolling(3, min_periods=1).mean()


def sig_flow_fade(df: pd.DataFrame, **kw) -> pd.Series:
    z = _z(df["signed_flow"], 96)
    return -z


def sig_intensity_dir(df: pd.DataFrame, **kw) -> pd.Series:
    act = _z(df["n_ticks"], 96)
    d = np.sign(df["mid_ret"])
    return act * d


def sig_intensity_flow(df: pd.DataFrame, **kw) -> pd.Series:
    act = (_z(df["n_ticks"], 96)).clip(lower=0)
    return df["signed_flow"] * act


def sig_quiet_rev(df: pd.DataFrame, **kw) -> pd.Series:
    quiet = (-_z(df["n_ticks"], 96)).clip(lower=0)
    return -df["mid_ret"].rolling(3, min_periods=1).sum() * quiet * 1000


def sig_spread_exp_rev(df: pd.DataFrame, **kw) -> pd.Series:
    exp_ = _z(df["spread_mean_bps"], 96)
    return -df["mid_ret"].rolling(2, min_periods=1).sum() * exp_.clip(lower=0) * 1000


def sig_spread_contr_cont(df: pd.DataFrame, **kw) -> pd.Series:
    contr = (-_z(df["spread_mean_bps"], 96)).clip(lower=0)
    return np.sign(df["mid_ret"]) * contr


def sig_spread_spike_fade(df: pd.DataFrame, **kw) -> pd.Series:
    spike = _safe_div(df["spread_max_bps"], df["spread_mean_bps"].replace(0, np.nan)) - 1
    return -(spike.fillna(0)) * np.sign(df["mid_ret"])


def sig_impact_cont(df: pd.DataFrame, **kw) -> pd.Series:
    imp = _safe_div(df["mid_ret"].abs(), df["n_ticks"].replace(0, np.nan))
    iz = _z(imp.fillna(0), 96)
    return np.sign(df["mid_ret"]) * iz.clip(lower=0)


def sig_low_impact_fade(df: pd.DataFrame, **kw) -> pd.Series:
    imp = _safe_div(df["mid_ret"].abs(), df["n_ticks"].replace(0, np.nan))
    lo = (-_z(imp.fillna(0), 96)).clip(lower=0)
    return -np.sign(df["mid_ret"]) * lo


def sig_bar_persist(df: pd.DataFrame, **kw) -> pd.Series:
    d = np.sign(df["mid_ret"])
    return d.rolling(6, min_periods=1).sum() / 6


def sig_quote_run(df: pd.DataFrame, **kw) -> pd.Series:
    # proxy for quote-run length: EMA of up_frac dominance
    dom = df["up_frac"] - df["dn_frac"]
    return dom.ewm(span=6, min_periods=1).mean()


def sig_eur_gbp_flow(df: pd.DataFrame, **kw) -> pd.Series:
    all_data = kw.get("all_data", {})
    lead = all_data.get("EURUSDm")
    if lead is None:
        return pd.Series(0.0, index=df.index)
    s = lead.set_index("time")["signed_flow"]
    aligned = s.shift(1).reindex(pd.DatetimeIndex(df["time"]), method="ffill")
    return pd.Series(aligned.fillna(0).to_numpy(), index=df.index)


def sig_sp500_nasdac_flow(df: pd.DataFrame, **kw) -> pd.Series:
    all_data = kw.get("all_data", {})
    lead = all_data.get("US500m")
    if lead is None:
        return pd.Series(0.0, index=df.index)
    s = lead.set_index("time")["signed_flow"]
    aligned = s.shift(1).reindex(pd.DatetimeIndex(df["time"]), method="ffill")
    return pd.Series(aligned.fillna(0).to_numpy(), index=df.index)


def sig_gold_aud_flow(df: pd.DataFrame, **kw) -> pd.Series:
    all_data = kw.get("all_data", {})
    lead = all_data.get("XAUUSDm")
    if lead is None:
        return pd.Series(0.0, index=df.index)
    s = lead.set_index("time")["signed_flow"]
    aligned = s.shift(1).reindex(pd.DatetimeIndex(df["time"]), method="ffill")
    return pd.Series(aligned.fillna(0).to_numpy(), index=df.index)


def sig_flow_x_spread(df: pd.DataFrame, **kw) -> pd.Series:
    tight = (-_z(df["spread_mean_bps"], 96)).clip(lower=0)
    return df["signed_flow"] * tight


def sig_spike_breakout(df: pd.DataFrame, **kw) -> pd.Series:
    hi = df["mid_high"].rolling(36).max()
    lo = df["mid_low"].rolling(36).min()
    mid_rng = ((hi + lo) / 2).replace(0, np.nan)
    brk = np.sign(df["mid_close"] - mid_rng)
    act = (_z(df["n_ticks"], 96)).clip(lower=0)
    return brk * act.fillna(0)


SIGNALS: Dict[str, Callable] = {h.signal: globals()[h.signal] for h in HYPOTHESES}


# ═══════════════════════════════════════════════════════════════════════
# ENGINE (M5-correct annualization; identical methodology to C4–C6)
# ═══════════════════════════════════════════════════════════════════════


def bt(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
    cost: float,
) -> Tuple[float, float, float, int]:
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["mid_close"].pct_change(hp).shift(-hp)
    strat = pos * fwd
    n_trades = int(pos.diff().abs().sum())
    clean = strat.dropna()
    if len(clean) < 30 or clean.std() == 0:
        return 0.0, 0.0, 0.0, n_trades
    ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp)
    sharpe = float(clean.mean() / clean.std() * ann)
    cum = (1 + clean).cumprod()
    dd = float(((cum - cum.cummax()) / cum.cummax()).min())
    net_ret = float(clean.sum()) - n_trades * cost
    return sharpe, net_ret, dd, n_trades


def _threshold(sig: pd.Series) -> pd.Series:
    thr = sig.rolling(20, min_periods=10).std() * 0.5
    out = sig.where(sig.abs() > thr, 0)
    return out.replace([np.inf, -np.inf], 0).fillna(0)


def wf_validate(
    df: pd.DataFrame,
    func: Callable,
    hp: int,
    n_folds: int = 4,
    all_data: Dict[str, pd.DataFrame] | None = None,
) -> Tuple[float, float]:
    fold_size = len(df) // (n_folds + 1)
    fold_sharpes: List[float] = []
    for i in range(n_folds):
        s = fold_size * (i + 1)
        e = min(s + fold_size, len(df))
        if e - s < 100:
            continue
        try:
            kw = {"all_data": all_data} if all_data else {}
            sig = _threshold(func(df.iloc[s:e], **kw))
            sh, _, _, _ = bt(df.iloc[s:e], sig, hp, CostModel.BASE)
            fold_sharpes.append(sh)
        except Exception:
            fold_sharpes.append(0.0)
    if not fold_sharpes:
        return 0.0, 0.0
    cons = sum(1 for s in fold_sharpes if s > 0) / len(fold_sharpes)
    return cons, float(np.mean(fold_sharpes))


def permutation_test(
    df: pd.DataFrame,
    func: Callable,
    hp: int,
    n_permutations: int = 100,
    all_data: Dict[str, pd.DataFrame] | None = None,
) -> float:
    try:
        kw = {"all_data": all_data} if all_data else {}
        real_sig = _threshold(func(df, **kw))
        real_sharpe, _, _, _ = bt(df, real_sig, hp, CostModel.BASE)
    except Exception:
        return 1.0
    if real_sharpe <= 0:
        return 1.0
    cnt = 0
    for _ in range(n_permutations):
        shuffled = pd.Series(real_sig.sample(frac=1.0, replace=False).values, index=df.index)
        ps, _, _, _ = bt(df, shuffled, hp, CostModel.BASE)
        if ps >= real_sharpe:
            cnt += 1
    return cnt / n_permutations


def regime_analysis(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["mid_close"].pct_change(hp).shift(-hp)
    strat = (pos * fwd).dropna()
    ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp)

    year_sharpes: Dict[str, float] = {}
    session_sharpes: Dict[str, float] = {}
    if "time" not in df.columns or strat.empty:
        return year_sharpes, session_sharpes

    years = pd.to_datetime(df.loc[strat.index, "time"]).dt.year
    for yr, grp in strat.groupby(years):
        if len(grp) < 50 or grp.std() == 0:
            continue
        year_sharpes[str(yr)] = float(grp.mean() / grp.std() * ann)

    hours = pd.to_datetime(df.loc[strat.index, "time"]).dt.hour
    for name, (lo, hi) in SESSION_BOUNDS_UTC.items():
        r = strat[(hours >= lo) & (hours < hi)]
        if len(r) < 50 or r.std() == 0:
            continue
        session_sharpes[name] = float(r.mean() / r.std() * ann)

    return year_sharpes, session_sharpes


# ═══════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════


def run(data_dir: str = DATA_DIR) -> List[MicroHypResult]:
    data: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(data_dir, f"{s}_M5micro.csv")
        if os.path.exists(p):
            data[s] = pd.read_csv(p, parse_dates=["time"])
            print(f"  Loaded {s}: {len(data[s])} micro bars ({data[s]['time'].iloc[0]} → {data[s]['time'].iloc[-1]})")
    if not data:
        print("ERROR: no microstructure bars found — run tick_data_puller first")
        return []

    results: List[MicroHypResult] = []
    n_evaluations = 0
    for h in HYPOTHESES:
        func = SIGNALS.get(h.signal)
        if func is None:
            print(f"SKIP {h.hid}: no signal function")
            continue
        print(f"\n{'=' * 60}\n{h.hid}: {h.description} [{h.family}]")

        best, best_score = None, -999.0
        for hp in HORIZONS:
            gross_vals, net_vals, adv_vals, dd_vals = [], [], [], []
            total_trades = 0
            sym_net: Dict[str, float] = {}

            for s, df in data.items():
                try:
                    kw = {"all_data": data} if h.family == "lead_lag" else {}
                    sig = _threshold(func(df, **kw))
                    g, _, _, t = bt(df, sig, hp, 0)
                    nb, _, _, _ = bt(df, sig, hp, CostModel.BASE)
                    na, _, dd, _ = bt(df, sig, hp, CostModel.ADVERSE)
                    gross_vals.append(g)
                    net_vals.append(nb)
                    adv_vals.append(na)
                    dd_vals.append(dd)
                    total_trades += t
                    sym_net[s] = nb
                except Exception:
                    continue

            if not gross_vals:
                continue
            n_evaluations += 1

            ag = float(np.mean(gross_vals))
            anb = float(np.mean(net_vals))
            ana = float(np.mean(adv_vals))
            mdd = float(min(dd_vals))

            anchor_name = next((s for s in ["EURUSDm", "XAUUSDm"] if s in data), list(data)[0])
            anchor = data[anchor_name]
            all_data_arg: Dict[str, pd.DataFrame] | None = data if h.family == "lead_lag" else None
            wf_cons, wf_oos = wf_validate(anchor, func, hp, all_data=all_data_arg)
            deg = 1 - anb / ag if abs(ag) > 1e-3 else 1.0

            r = MicroHypResult(
                hid=h.hid,
                family=h.family,
                description=h.description,
                hp=hp,
                gross_sharpe=ag,
                net_base=anb,
                net_adverse=ana,
                max_dd=mdd,
                trades=total_trades,
                wf_consistency=wf_cons,
                wf_oos_sharpe=wf_oos,
                degradation=deg,
                sym_sharpes=sym_net,
            )

            try:
                kw = {"all_data": data} if h.family == "lead_lag" else {}
                sig_f = _threshold(func(anchor, **kw))
                yr, sess = regime_analysis(anchor, sig_f, hp)
                r.year_sharpes = yr
                r.session_sharpes = sess
            except Exception:
                pass

            try:
                r.permutation_p = permutation_test(anchor, func, hp, 100, all_data=all_data_arg)
            except Exception:
                r.permutation_p = 1.0

            r.verdict, r.reasons, r.primary_failure = classify(r)

            print(
                f"  HP={hp} ({hp * 5:2d}m): gross={ag:+.3f} net={anb:+.3f} "
                f"adv={ana:+.3f} DD={mdd:.2f} WF={wf_cons:.0%} "
                f"perm_p={r.permutation_p:.3f} → {r.verdict.value}"
            )

            score = anb + wf_cons * 0.5 - r.permutation_p * 0.2
            if score > best_score:
                best_score, best = score, r

        results.append(
            best
            if best
            else MicroHypResult(
                hid=h.hid,
                family=h.family,
                description=h.description,
                hp=HORIZONS[0],
                verdict=Verdict.REJECTED,
                reasons=["no_data"],
                primary_failure="no_data",
            )
        )

    # ── Family-wise Bonferroni correction (one family: all hyp × horizon
    #    evaluations in this campaign). Verdicts re-run on the adjusted p;
    #    raw p is preserved on each result.
    family_size = max(1, n_evaluations)
    for r in results:
        r.permutation_p_bonferroni = min(1.0, r.permutation_p * family_size)
        r.bonferroni_family_size = family_size
        gated = replace(r, permutation_p=r.permutation_p_bonferroni)
        gated.verdict, gated.reasons, gated.primary_failure = classify(gated)
        r.verdict = gated.verdict
        r.reasons = gated.reasons
        r.primary_failure = gated.primary_failure

    n_total_trials = PRIOR_EVALUATIONS + n_evaluations
    print(
        f"\nFamily: {n_evaluations} evaluations Bonferroni-corrected "
        f"(cumulative intraday trials incl. frozen branch: {n_total_trials})"
    )
    return results


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════


def write_reports(results: List[MicroHypResult]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs("reports", exist_ok=True)
    groups: Dict[str, List[HypResult]] = defaultdict(list)
    for r in results:
        groups[r.verdict.value].append(r)
    surv = groups.get("supported", [])

    lines: List[str] = [
        "# CAMPAIGN 7 — BROKER-SPECIFIC MICROSTRUCTURE (REAL TICK QUOTES)",
        "",
        "**Information source:** Exness MT5 quote ticks → M5 micro bars "
        "(broker-specific microstructure, NOT institutional order flow)",
        "**Universe:** 8 instruments",
        f"**Generated:** {now}",
        f"**Hypotheses:** {len(results)} pre-registered across 7 families",
        f"**Costs:** base {CostModel.BASE * 10000:.0f}bps / adverse {CostModel.ADVERSE * 10000:.0f}bps",
        "**Multiple testing:** all hypothesis × horizon evaluations form one "
        "Bonferroni family; SUPPORTED requires p_adj ≤ 0.05. "
        "Cumulative intraday trials incl. frozen branch: "
        f"{PRIOR_EVALUATIONS} prior + current campaign.",
        "",
        "---",
        "",
        "## VERDICT DISTRIBUTION",
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
        hs = groups.get(v, [])
        if hs:
            lines.append(f"| **{v.upper()}** | {len(hs)} | {', '.join(x.hid for x in hs)} |")
    lines.extend(["", f"**Survivors: {len(surv)}/{len(results)}**", ""])

    top = sorted(results, key=lambda r: r.net_base, reverse=True)[:6]
    lines.extend(
        [
            "---",
            "",
            "## TOP CANDIDATES",
            "",
            "| ID | Family | HP | Net | Adv | DD | WF | Perm p | p_adj | Verdict |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for r in top:
        p_adj = getattr(r, "permutation_p_bonferroni", 1.0)
        lines.append(
            f"| {r.hid} | {r.family} | {r.hp * 5}m | {r.net_base:+.3f} | "
            f"{r.net_adverse:+.3f} | {r.max_dd:.2f} | "
            f"{r.wf_consistency:.0%} | {r.permutation_p:.3f} | "
            f"{p_adj:.3f} | "
            f"{r.verdict.value} |"
        )

    lines.extend(["---", "", "## DETAILED RESULTS", ""])
    for r in sorted(results, key=lambda x: x.net_base, reverse=True):
        icon = "🟢" if r.verdict == Verdict.SUPPORTED else "🟡" if r.verdict != Verdict.REJECTED else "🔴"
        npos = sum(1 for v in r.sym_sharpes.values() if v > 0)
        lines.extend(
            [
                f"### {icon} {r.hid} — {r.description} ({r.hp * 5}m, {r.verdict.value})",
                f"- gross/net/adverse: {r.gross_sharpe:+.3f} / {r.net_base:+.3f} / {r.net_adverse:+.3f}",
                f"- maxDD {r.max_dd:.2f} · trades {r.trades} · WF {r.wf_consistency:.0%} "
                f"(OOS {r.wf_oos_sharpe:+.3f}) · perm p {r.permutation_p:.3f} "
                f"(adj {getattr(r, 'permutation_p_bonferroni', 1.0):.3f}, family "
                f"{getattr(r, 'bonferroni_family_size', 0)})",
                f"- instruments positive: {npos}/{len(r.sym_sharpes)}",
                f"- primary failure: {r.primary_failure}",
                "",
            ]
        )

    md = "\n".join(lines) + "\n"
    with open(REPORT_MD, "w") as f:
        f.write(md)
    with open(REPORT_JSON, "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2)
    print(f"\nReports written: {REPORT_MD}, {REPORT_JSON}")


if __name__ == "__main__":
    res = run()
    write_reports(res)
    dist = Counter(r.verdict.value for r in res)
    print("\nFINAL VERDICT DISTRIBUTION:", dict(dist))
    print(f"Survival: {dist.get('supported', 0)}/{len(res)}")
