"""Campaign 5 — 30M Mechanism-Focused Intraday Investigation.

NOT another hypothesis-fishing expedition. This campaign carries forward the
specific mechanisms that survived Campaign 4's forensic analysis as *leads*,
pre-registering them alongside the small set of economically motivated
mechanisms that could plausibly strengthen at slower intraday horizons:

1.  NC-001..003  — SE-004 continuation: NY-close mean reversion (the single
                   best C4 candidate: net Sharpe +1.12, all-8-instrument
                   positive, but permutation p=0.11 → fragile).
2.  NR-001..002  — NY opening/closing range effects.
3.  MH-001..004  — multi-hour momentum and reversal.
4.  ST-001..002  — session transitions (C4 session decomposition showed the
                   only real structure was session-conditional).
5.  VR-001..002  — volatility expansion/contraction.
6.  XA-001..003  — cross-asset lead/lag continuations (XA-003 hit p=0.01 in C4).
7.  CM-001..002  — small number of structurally motivated composites.

Validation pipeline identical to Campaign 4:
costs → OOS walk-forward → permutation → stress → regime → drawdown.
No tuning. Verdicts are fail-closed.

Engine note: at M30 resolution there are 48 bars per trading day, so
annualization differs from Campaign 4 (96). Horizon grid: 1/2/4/8 bars =
30m / 1h / 2h / 4h.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Reuse Campaign 4's validated building blocks (signals are bar-size agnostic;
# verdict logic is horizon-count based, not annualization based).
from eigencapital.research.intraday.campaign4_15m import (
    SESSION_BOUNDS_UTC,
    UNIVERSE,
    CostModel,
    HypResult,
    Hypothesis,
    Verdict,
)
from eigencapital.research.intraday.campaign4_15m import (
    _rmean,
    _rstd,
    _safe_div,
    _session_mask,
    classify,
)

# ── Constants ───────────────────────────────────────────────────────────

HORIZONS = [1, 2, 4, 8]          # in M30 bars: 30m, 1h, 2h, 4h
TRADING_DAYS_PER_YEAR = 252
BARS_PER_TRADING_DAY = 48        # ~24h market / 30min (FX); indices ~13h but consistent convention with prior campaigns

DATA_DIR = "data/intraday_m30"
REPORT_JSON = "reports/campaign5_30m_map.json"
REPORT_MD = "reports/campaign5_30m_map.md"


# ═══════════════════════════════════════════════════════════════════════
# PRE-REGISTERED HYPOTHESES (18, mechanism-focused)
# ═══════════════════════════════════════════════════════════════════════

HYPOTHESES: List[Hypothesis] = [
    # A. SE-004 continuation — NY-close mean reversion (PRIMARY lead from C4)
    Hypothesis("NC-001", "ny_close_rev",
               "SE-004 continuation: NY-close mean reversion at 30M",
               "sig_ny_close",
               "End-of-day flattening creates reversion; best C4 candidate"),
    Hypothesis("NC-002", "ny_close_rev",
               "Late-NY fade (UTC 19-21 only)",
               "sig_late_ny_fade",
               "Reversion concentrates in final hours before NY close"),
    Hypothesis("NC-003", "ny_close_rev",
               "NY-close reversion x vol regime composite",
               "sig_ny_close_x_volreg",
               "SE-004 mechanism conditioned on volatility state"),

    # B. NY range effects
    Hypothesis("NR-001", "ny_range",
               "NY opening-range breakout (first hour range)",
               "sig_ny_open_range_break",
               "Break of first-hour NY range signals continuation"),
    Hypothesis("NR-002", "ny_range",
               "Intraday closing-range fade during NY",
               "sig_day_range_fade_ny",
               "Position within day range fades at NY extremes"),

    # C/D. Multi-hour momentum and reversal
    Hypothesis("MH-001", "multihour_mom",
               "2h momentum (4-bar continuation)",
               "sig_mom_4",
               "Directional persistence at 2h scale"),
    Hypothesis("MH-002", "multihour_mom",
               "4h momentum vol-adjusted (8-bar)",
               "sig_mom_8_voladj",
               "Vol-normalized persistence at 4h scale"),
    Hypothesis("MH-003", "multihour_rev",
               "Daily z-score reversal (48-bar lookback)",
               "sig_daily_zscore_rev",
               "One-day extremes revert at 30M resolution"),
    Hypothesis("MH-004", "multihour_rev",
               "Two-day VWAP deviation reversion",
               "sig_day_vwap_dev",
               "Deviation from 96-bar VWAP reverts"),

    # E. Session transitions (C4: only real structure was session-conditional)
    Hypothesis("ST-001", "session_transition",
               "Asia→London transition continuation",
               "sig_asia_london",
               "London inherits overnight direction"),
    Hypothesis("ST-002", "session_transition",
               "London/NY overlap momentum",
               "sig_overlap_mom",
               "Overlap is the strongest trending period"),

    # F. Volatility regimes
    Hypothesis("VR-101", "vol_regime",
               "Vol expansion momentum (20/80 windows)",
               "sig_vol_expansion_mom",
               "Expanding vol accompanies directional moves"),
    Hypothesis("VR-102", "vol_regime",
               "Vol contraction reversal (20/80 windows)",
               "sig_vol_contraction_rev",
               "Contracting vol precedes reversals"),

    # G. Cross-asset lead/lag continuations (XA-003 hit p=0.01 in C4)
    Hypothesis("XA-101", "cross_asset",
               "US500 leads XAUUSD inverse (C4 XA-003 continuation)",
               "sig_us500_xauusd_lead",
               "Equity weakness leads gold rally; strongest C4 stat signal"),
    Hypothesis("XA-102", "cross_asset",
               "USTEC leads EURUSD (C4 XA-002 continuation)",
               "sig_ustec_eurusd_lead",
               "Tech index leads FX risk appetite"),
    Hypothesis("XA-103", "cross_asset",
               "USOIL leads USDJPY (C4 XA-004 continuation)",
               "sig_usoil_usdjpy_lead",
               "Oil leads JPY through risk channel"),

    # H. Composites (small, structurally motivated only)
    Hypothesis("CM-101", "composite",
               "Momentum gated to NY session",
               "sig_mom_ny_only",
               "Momentum works only during liquid NY hours"),
    Hypothesis("CM-102", "composite",
               "Range breakout x volume confirmation",
               "sig_break_x_vol",
               "Volume-confirmed breakouts are genuine"),
]

for h in HYPOTHESES:
    object.__setattr__(h, "phash", h.compute_hash())


# ═══════════════════════════════════════════════════════════════════════
# NEW SIGNAL FUNCTIONS (30M-specific mechanisms)
# ═══════════════════════════════════════════════════════════════════════

def sig_late_ny_fade(df: pd.DataFrame, **kw) -> pd.Series:
    """Fade late-NY moves (UTC 19:00–21:00) — final-hours position squaring."""
    mom = df["close"].pct_change(4)
    mask = _hours_mask(df, 19, 21)
    return -mom * mask.astype(float)


def sig_ny_close_x_volreg(df: pd.DataFrame, **kw) -> pd.Series:
    """NY-close mean reversion conditioned on vol regime."""
    base = sig_ny_close_local(df)
    r = df["close"].pct_change(1)
    rv = _rstd(r, 40)
    regime = _safe_div(rv, _rmean(rv, 160)).fillna(1.0)
    return base * regime


def sig_ny_open_range_break(df: pd.DataFrame, **kw) -> pd.Series:
    """NY opening-range breakout: first hour (16:00–17:00 UTC) high/low."""
    t = pd.to_datetime(df["time"])
    dates = t.dt.date
    hours = t.dt.hour
    in_or = hours == 16
    or_h = df.loc[in_or].groupby(dates[in_or])["high"].max()
    or_l = df.loc[in_or].groupby(dates[in_or])["low"].min()
    dh = dates.map(or_h)
    dl = dates.map(or_l)
    rng = (dh - dl).replace(0, np.nan)
    pos = ((df["close"] - dl) / rng - 0.5) * 2.0
    active = (hours >= 17) & (hours < 21)
    return pos.where(active, 0.0).fillna(0.0)


def sig_day_range_fade_ny(df: pd.DataFrame, **kw) -> pd.Series:
    """Fade position within the day-so-far range during NY session."""
    t = pd.to_datetime(df["time"])
    dates = t.dt.date
    day_high = df["high"].groupby(dates).cummax()
    day_low = df["low"].groupby(dates).cummin()
    rng = (day_high - day_low).replace(0, np.nan)
    pos = (df["close"] - day_low) / rng
    mask = _hours_mask(df, 16, 21)
    return -(pos - 0.5) * mask.astype(float)


def sig_daily_zscore_rev(df: pd.DataFrame, **kw) -> pd.Series:
    """Z-score over one trading day of M30 bars (48), reversed."""
    mu = _rmean(df["close"], 48)
    sigma = _rstd(df["close"], 48)
    return -_safe_div(df["close"] - mu, sigma)


def sig_day_vwap_dev(df: pd.DataFrame, **kw) -> pd.Series:
    """Deviation from rolling two-day VWAP (96 bars), reversed."""
    cum_v = df["tick_volume"].rolling(96, min_periods=8).sum()
    cum_pv = (df["close"] * df["tick_volume"]).rolling(96, min_periods=8).sum()
    vwap = _safe_div(cum_pv, cum_v)
    return -_safe_div(df["close"] - vwap, vwap)


def sig_mom_ny_only(df: pd.DataFrame, **kw) -> pd.Series:
    """8-bar momentum gated to NY session (UTC 16–21)."""
    mom = df["close"].pct_change(8)
    mask = _hours_mask(df, 16, 21)
    return mom * mask.astype(float)


# ── Local helpers ───────────────────────────────────────────────────────

def _hours_mask(df: pd.DataFrame, lo: int, hi: int) -> pd.Series:
    if "time" not in df.columns:
        return pd.Series(True, index=df.index)
    hours = pd.to_datetime(df["time"]).dt.hour
    return (hours >= lo) & (hours < hi)


def sig_ny_close_local(df: pd.DataFrame, **kw) -> pd.Series:
    """Local alias to avoid importing private signal twice."""
    mom = df["close"].pct_change(4)
    mask = _hours_mask(df, 16, 21)
    return -mom * mask.astype(float)


SIGNALS: Dict[str, Callable] = {
    "sig_ny_close": sig_ny_close_local,
    "sig_late_ny_fade": sig_late_ny_fade,
    "sig_ny_close_x_volreg": sig_ny_close_x_volreg,
    "sig_ny_open_range_break": sig_ny_open_range_break,
    "sig_day_range_fade_ny": sig_day_range_fade_ny,
    "sig_mom_4": None,        # filled below from campaign4 registry
    "sig_mom_8_voladj": None,
    "sig_daily_zscore_rev": sig_daily_zscore_rev,
    "sig_day_vwap_dev": sig_day_vwap_dev,
    "sig_asia_london": None,
    "sig_overlap_mom": None,
    "sig_vol_expansion_mom": None,
    "sig_vol_contraction_rev": None,
    "sig_us500_xauusd_lead": None,
    "sig_ustec_eurusd_lead": None,
    "sig_usoil_usdjpy_lead": None,
    "sig_mom_ny_only": sig_mom_ny_only,
    "sig_break_x_vol": None,
}

from eigencapital.research.intraday.campaign4_15m import SIGNALS as C4_SIGNALS  # noqa: E402

for k in list(SIGNALS):
    if SIGNALS[k] is None:
        SIGNALS[k] = C4_SIGNALS[k]


# ═══════════════════════════════════════════════════════════════════════
# ENGINE (30M-correct annualization)
# ═══════════════════════════════════════════════════════════════════════

def bt(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
    cost: float,
) -> Tuple[float, float, float, int]:
    """Backtest with 30M-correct annualization."""
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["close"].pct_change(hp).shift(-hp)
    strat = pos * fwd
    n_trades = int(pos.diff().abs().sum())
    tc = n_trades * cost
    clean = strat.dropna()
    if len(clean) < 30 or clean.std() == 0:
        return 0.0, 0.0, 0.0, n_trades
    bars_per_year = TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp
    ann = np.sqrt(bars_per_year)
    sharpe = float(clean.mean() / clean.std() * ann)
    cum = (1 + clean).cumprod()
    dd = float(((cum - cum.cummax()) / cum.cummax()).min())
    return sharpe, float(clean.sum() - tc), dd, n_trades


def _threshold(sig: pd.Series) -> pd.Series:
    thr = sig.rolling(10, min_periods=5).std() * 0.5
    return sig.where(sig.abs() > thr, 0)


def wf_validate(
    df: pd.DataFrame,
    func: Callable,
    hp: int,
    n_folds: int = 5,
    all_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> Tuple[float, float]:
    fold_size = len(df) // (n_folds + 1)
    fold_sharpes: List[float] = []
    for i in range(n_folds):
        s = fold_size * (i + 1)
        e = min(s + fold_size, len(df))
        if e - s < 50:
            continue
        try:
            kw = {"all_data": all_data} if all_data else {}
            sig = _threshold(func(df.iloc[s:e], **kw).fillna(0))
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
    n_permutations: int = 100,
    all_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> float:
    try:
        kw = {"all_data": all_data} if all_data else {}
        real_sig = _threshold(func(df, **kw).fillna(0))
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
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["close"].pct_change(hp).shift(-hp)
    strat = (pos * fwd).dropna()
    bars_per_year = TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp
    ann = np.sqrt(bars_per_year)

    year_sharpes: Dict[str, float] = {}
    session_sharpes: Dict[str, float] = {}
    if "time" not in df.columns:
        return year_sharpes, session_sharpes

    years = pd.to_datetime(df.loc[strat.index, "time"]).dt.year
    for yr, grp in strat.groupby(years):
        if len(grp) < 30 or grp.std() == 0:
            continue
        year_sharpes[str(yr)] = float(grp.mean() / grp.std() * ann)

    hours = pd.to_datetime(df.loc[strat.index, "time"]).dt.hour
    for sess_name, (lo, hi) in SESSION_BOUNDS_UTC.items():
        sess_ret = strat[(hours >= lo) & (hours < hi)]
        if len(sess_ret) < 30 or sess_ret.std() == 0:
            continue
        session_sharpes[sess_name] = float(sess_ret.mean() / sess_ret.std() * ann)

    return year_sharpes, session_sharpes


# ═══════════════════════════════════════════════════════════════════════
# CAMPAIGN RUNNER
# ═══════════════════════════════════════════════════════════════════════

def run(data_dir: str = DATA_DIR) -> List[HypResult]:
    data: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(data_dir, f"{s}_M30.csv")
        if os.path.exists(p):
            data[s] = pd.read_csv(p, parse_dates=["time"])
            print(f"  Loaded {s}: {len(data[s])} bars "
                  f"({data[s]['time'].iloc[0]} → {data[s]['time'].iloc[-1]})")
    if not data:
        print("ERROR: No M30 data found")
        return []

    results: List[HypResult] = []
    for h in HYPOTHESES:
        func = SIGNALS.get(h.signal)
        if func is None:
            print(f"SKIP {h.hid}: no signal function")
            continue

        print(f"\n{'='*60}")
        print(f"{h.hid}: {h.description} [{h.family}]")

        is_cross_asset = h.family == "cross_asset"
        best, best_score = None, -999

        for hp in HORIZONS:
            gross_vals, net_vals, adv_vals, dd_vals = [], [], [], []
            total_trades = 0

            for s, df in data.items():
                try:
                    kw = {"all_data": data} if is_cross_asset else {}
                    sig = _threshold(func(df, **kw).fillna(0))
                    g, _, _, t = bt(df, sig, hp, 0)
                    nb, _, _, _ = bt(df, sig, hp, CostModel.BASE)
                    na, _, dd, _ = bt(df, sig, hp, CostModel.ADVERSE)
                    gross_vals.append(g)
                    net_vals.append(nb)
                    adv_vals.append(na)
                    dd_vals.append(dd)
                    total_trades += t
                except Exception:
                    continue

            if not gross_vals:
                continue

            ag = float(np.mean(gross_vals))
            anb = float(np.mean(net_vals))
            ana = float(np.mean(adv_vals))
            mdd = float(min(dd_vals))

            anchor = data.get("EURUSDm", list(data.values())[0])
            wf_kw = {"all_data": data} if is_cross_asset else {}
            wf_cons, wf_oos = wf_validate(anchor, func, hp, n_folds=5, **wf_kw)
            deg = 1 - (anb / ag) if abs(ag) > 0.001 else 1.0

            r = HypResult(
                hid=h.hid, family=h.family, description=h.description, hp=hp,
                gross_sharpe=ag, net_base=anb, net_adverse=ana, max_dd=mdd,
                trades=total_trades, wf_consistency=wf_cons, wf_oos_sharpe=wf_oos,
                degradation=deg,
            )

            try:
                kw = {"all_data": data} if is_cross_asset else {}
                sig_final = _threshold(func(anchor, **kw).fillna(0))
                yr_sh, sess_sh = regime_analysis(anchor, sig_final, hp)
                r.year_sharpes = yr_sh
                r.session_sharpes = sess_sh
            except Exception:
                pass

            try:
                perm_kw = {"all_data": data} if is_cross_asset else {}
                r.permutation_p = permutation_test(
                    anchor, func, hp, n_permutations=100, **perm_kw
                )
            except Exception:
                r.permutation_p = 1.0

            # Per-instrument net Sharpes
            sym_net: Dict[str, float] = {}
            for s, df in data.items():
                try:
                    kw = {"all_data": data} if is_cross_asset else {}
                    sig = _threshold(func(df, **kw).fillna(0))
                    nb, _, _, _ = bt(df, sig, hp, CostModel.BASE)
                    sym_net[s] = nb
                except Exception:
                    continue
            r.sym_sharpes = sym_net

            r.verdict, r.reasons, r.primary_failure = classify(r)

            print(f"  HP={hp:2d} bars ({hp*30:3d}m): gross={ag:+.3f} "
                  f"net={anb:+.3f} adv={ana:+.3f} DD={mdd:.3f} "
                  f"WF={wf_cons:.0%} perm_p={r.permutation_p:.3f} "
                  f"→ {r.verdict.value}")

            score = anb + wf_cons * 0.5 - r.permutation_p * 0.2
            if score > best_score:
                best_score = score
                best = r

        results.append(best if best else HypResult(
            hid=h.hid, family=h.family, description=h.description,
            hp=HORIZONS[0], verdict=Verdict.REJECTED,
            reasons=["no_data"], primary_failure="no_data",
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════

def write_reports(results: List[HypResult]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs("reports", exist_ok=True)

    groups: Dict[str, List[HypResult]] = defaultdict(list)
    for r in results:
        groups[r.verdict.value].append(r)

    surv = groups.get("supported", [])
    frag = [r for r in results if r.verdict in (
        Verdict.FRAGILE, Verdict.COST_SENSITIVE, Verdict.REGIME_DEPENDENT)]

    lines: List[str] = [
        "# CAMPAIGN 5 — 30M MECHANISM-FOCUSED INTRADAY INVESTIGATION",
        "",
        "**Universe:** 8 instruments (Exness MT5)",
        "**Timeframe:** 30-minute (M30)",
        "**Bars:** ~50,000 per symbol (~4 years, Apr 2022 – Aug 2026)",
        f"**Generated:** {now}",
        f"**Hypotheses:** {len(results)} (mechanism-focused, incl. SE-004 continuation)",
        f"**Horizons:** 30m / 1h / 2h / 4h",
        f"**Costs:** base {CostModel.BASE*10000:.0f}bps, adverse {CostModel.ADVERSE*10000:.0f}bps",
        "",
        "---", "",
        "## VERDICT DISTRIBUTION", "",
        "| Verdict | Count | Hypotheses |",
        "|---|---|---|",
    ]
    for v in ["rejected", "regime_dependent", "cost_sensitive",
              "fragile", "inconclusive", "supported"]:
        hs = groups.get(v, [])
        if hs:
            lines.append(f"| **{v.upper()}** | {len(hs)} | "
                         f"{', '.join(x.hid for x in hs)} |")
    lines.extend(["", f"**Survivors: {len(surv)}/{len(results)}**", ""])

    # Failure modes
    lines.extend([
        "---", "", "## FAILURE MODE DISTRIBUTION", "",
        "| Failure Mode | Count |", "|---|---|",
    ])
    fail_counts: Dict[str, int] = defaultdict(int)
    for r in results:
        fail_counts[r.primary_failure or "unknown"] += 1
    for fm, cnt in sorted(fail_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {fm} | {cnt} |")
    lines.append("")

    # Top candidates
    top = sorted(results, key=lambda r: r.net_base, reverse=True)[:5]
    lines.extend([
        "---", "", "## TOP CANDIDATES", "",
        "| # | ID | Family | HP | Net Sharpe | Adv Sharpe | MaxDD | WF | Perm p | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])
    for i, r in enumerate(top, 1):
        lines.append(
            f"| {i} | {r.hid} | {r.family} | {r.hp*30}m | {r.net_base:+.3f} | "
            f"{r.net_adverse:+.3f} | {r.max_dd:.2f} | {r.wf_consistency:.0%} | "
            f"{r.permutation_p:.3f} | {r.verdict.value} |"
        )

    # Detailed per-hypothesis
    lines.extend(["---", "", "## DETAILED RESULTS", ""])
    for r in results:
        icon = ("🟢" if r.verdict == Verdict.SUPPORTED else
                "🟡" if r.verdict != Verdict.REJECTED else "🔴")
        lines.extend([
            f"### {icon} {r.hid} — {r.description}",
            f"**Family:** {r.family} | **HP:** {r.hp*30}m "
            f"| **Verdict:** {r.verdict.value}", "",
            "| Metric | Value |", "|---|---|",
            f"| Gross / Net / Adverse Sharpe | {r.gross_sharpe:+.3f} / "
            f"{r.net_base:+.3f} / {r.net_adverse:+.3f} |",
            f"| Max DD | {r.max_dd:.3f} |",
            f"| Trades | {r.trades} |",
            f"| WF Consistency / OOS Sharpe | {r.wf_consistency:.0%} / "
            f"{r.wf_oos_sharpe:+.3f} |",
            f"| Permutation p | {r.permutation_p:.3f} |",
            f"| Primary Failure | {r.primary_failure} |", "",
        ])
        if r.session_sharpes:
            ss = ", ".join(f"{k}: {v:+.2f}" for k, v in
                           sorted(r.session_sharpes.items()))
            lines.append(f"**Sessions:** {ss}")
        if r.year_sharpes:
            ys = ", ".join(f"{k}: {v:+.2f}" for k, v in
                           sorted(r.year_sharpes.items()))
            lines.append(f"**Years:** {ys}")
        if r.sym_sharpes:
            npos = sum(1 for v in r.sym_sharpes.values() if v > 0)
            lines.append(f"**Per-instrument:** {npos}/{len(r.sym_sharpes)} positive")
        lines.append("")

    # Combined intraday summary
    lines.extend([
        "---", "",
        "## COMBINED INTRADAY RESEARCH (Campaigns 1–5)", "",
        "| Campaign | Timeframe | Hypotheses | Supported | Fragile+ |",
        "|---|---|---|---|---|",
        "| 1 | M5 price | 24 | 0 | 0 |",
        "| 2 | M5 microstructure | 20 | 0 | 0 |",
        "| 3 | M1 order-flow | 16 | 0 | 1 |",
        "| 4 | 15M multi-family | 31 | 0 | 15 |",
        f"| 5 | 30M mechanism-focused | {len(results)} | {len(surv)} | {len(frag)} |",
        f"| **Total** | | **{91+len(results)}** | **{len(surv)}** | |",
        "",
    ])

    if surv:
        lines.append("**SURVIVOR(S) FOUND — proceed to independent confirmation (1H) "
                     "before any fidelity-ladder step.**")
    else:
        lines.extend([
            "**No supported survivor at 30M.** If this holds, the remaining step "
            "of the intraday ladder is 1H confirmation of any fragile leads.",
        ])

    md = "\n".join(lines) + "\n"
    with open(REPORT_MD, "w") as f:
        f.write(md)

    with open(REPORT_JSON, "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2)

    print(f"\nReports written: {REPORT_MD}, {REPORT_JSON}")


if __name__ == "__main__":
    import sys
    res = run(sys.argv[1] if len(sys.argv) > 1 else DATA_DIR)
    write_reports(res)
    from collections import Counter
    dist = Counter(r.verdict.value for r in res)
    print("\nFINAL VERDICT DISTRIBUTION:", dict(dist))
    print(f"Survival: {dist.get('supported', 0)}/{len(res)}")
