"""Campaign R5 - Swing Breadth executor.

Implements research/campaigns/R5_SWING_BREADTH_PREREGISTRATION.md exactly:
16 pre-registered daily-horizon hypotheses on the frozen 38-instrument D1
snapshot, point-in-time membership, per-flip net accounting, purged+
embargoed walk-forward, permutation significance, ONE Bonferroni family,
cumulative trial ledger, deflated Sharpe for survivors. No tuning after
results.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from typing import Dict

import numpy as np
import pandas as pd

from eigencapital.analytics.validation.deflated_sharpe import (
    deflated_sharpe_ratio,
)
from eigencapital.analytics.validation.walk_forward import purged_walk_forward
from eigencapital.research.intraday.net_accounting import bt_net

DATA_DIR = "data/mt5"
MANIFEST_PATH = "data/mt5/R5_data_manifest.json"
REPORT_JSON = "reports/r5_swing_breadth.json"
REPORT_MD = "reports/r5_swing_breadth.md"

COST_ONE_WAY_BASE = 7.5e-4      # 15 bps round-trip equivalent
COST_ONE_WAY_ADVERSE = 12.5e-4  # 25 bps

PRIOR_EVALUATIONS = 27          # R2(16) + R3(4) + R4(7)
FAMILY_SIZE = 16
CUMULATIVE_TRIALS = PRIOR_EVALUATIONS + FAMILY_SIZE  # 43

FAMILY_P_MAX = 0.05
CUMULATIVE_P_MAX = 0.05

GATES = {
    "net_sharpe_min": 0.50,
    "net_sharpe_adverse_min": 0.30,
    "wf_consistency_min": 0.50,
    "max_dd_limit": -0.25,
    "degradation_max": 2.0,
    "pct_positive_years_min": 0.60,
}
WF_TRAIN, WF_TEST, WF_PURGE, WF_EMBARGO = 504, 126, 5, 5


# -- Data & membership ----------------------------------------------------


def load_snapshot(data_dir: str = DATA_DIR) -> Dict[str, pd.DataFrame]:
    data: Dict[str, pd.DataFrame] = {}
    for f in sorted(os.listdir(data_dir)):
        if not f.endswith("_D1.csv"):
            continue
        sym = f.replace("_D1.csv", "")
        df = pd.read_csv(os.path.join(data_dir, f))
        tcol = df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol]).dt.tz_localize(None)
        df = df.rename(columns={tcol: "time"}).sort_values("time").set_index("time")
        data[sym] = df
    if not data:
        raise ValueError(f"no *_D1.csv under {data_dir}")
    return data


def verify_snapshot(data_dir: str = DATA_DIR, manifest_path: str = MANIFEST_PATH) -> bool:
    """Recompute combined sha256 against the frozen pre-registration manifest."""
    with open(manifest_path) as f:
        frozen = json.load(f)
    h = hashlib.sha256()
    for name in sorted(os.listdir(data_dir)):
        if not name.endswith("_D1.csv"):
            continue
        with open(os.path.join(data_dir, name), "rb") as fh:
            h.update(hashlib.sha256(fh.read()).hexdigest().encode())
    ok = h.hexdigest() == frozen["combined_sha256"]
    if not ok:
        print("SNAPSHOT MISMATCH: data changed since pre-registration freeze")
    return ok


def build_membership(data: Dict[str, pd.DataFrame]):
    from eigencapital.data.catalogue.membership import (
        UniverseMembership,
        UniverseMembershipRegistry,
    )

    reg = UniverseMembershipRegistry()
    for sym, df in sorted(data.items()):
        reg.add(UniverseMembership(sym, "r5_universe", df.index.min().strftime("%Y-%m-%d")))
    return reg


def member_frame(data: Dict[str, pd.DataFrame], col: str) -> pd.DataFrame:
    """Wide column frame; NaN outside each instrument's actual history."""
    idx = sorted(set().union(*[set(df.index) for df in data.values()]))
    out = {}
    for sym, df in data.items():
        s = df[col].reindex(idx)
        s[(s.index < df.index.min()) | (s.index > df.index.max())] = np.nan
        out[sym] = s
    return pd.DataFrame(out)


# -- Signal primitives -----------------------------------------------------


def _zscore(s: pd.Series, n: int) -> pd.Series:
    m = s.rolling(n, min_periods=n // 2).mean()
    sd = s.rolling(n, min_periods=n // 2).std()
    return (s - m) / sd.replace(0, np.nan)


def _tercile_ls(score: pd.DataFrame, min_names: int = 12) -> pd.DataFrame:
    """Row-wise +1 top tercile / -1 bottom tercile among non-NaN scores."""

    def _one(row: pd.Series) -> pd.Series:
        v = row.dropna()
        out = pd.Series(0.0, index=row.index)
        k = len(v)
        if k < min_names:
            return out
        ordered = v.sort_values()
        cut = max(1, k // 3)
        out[ordered.index[:cut]] = -1.0
        out[ordered.index[-cut:]] = 1.0
        return out

    return score.apply(_one, axis=1)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    # loss==0 with gain>0 -> rs=inf -> RSI=100 (pure uptrend must NOT be NaN)
    rs = gain / loss
    return 100 - 100 / (1 + rs)


# -- The locked slate: 16 position builders --------------------------------
# Each returns a wide DataFrame of target positions; NaN treated as flat.
# Positions enter on the NEXT bar inside bt_net (no look-ahead).


def _hold(pos: pd.DataFrame, days: int) -> pd.DataFrame:
    """Hold non-zero positions for `days` bars."""
    return pos.replace(0, np.nan).ffill(limit=days - 1).fillna(0.0)


def build_trend001(px, vol, members) -> pd.DataFrame:
    r = px.pct_change(252) - px.pct_change(21)
    return _hold(np.sign(r), 21)


def build_trend002(px, vol, members) -> pd.DataFrame:
    slope = px.pct_change(63) / (vol * np.sqrt(63))
    accel = slope - slope.shift(21)
    return _hold(np.sign(accel), 21)


def build_trend003(px, vol, members) -> pd.DataFrame:
    high = px.rolling(252, min_periods=126).max()
    dist = px / high
    sig = pd.DataFrame(np.where(dist > 0.80, 1.0, np.nan),
                       index=px.index, columns=px.columns)
    return _hold(sig, 21)


def _cs_ls(score: pd.DataFrame, hold: int) -> pd.DataFrame:
    return _hold(_tercile_ls(score), hold)


def build_mom001(px, vol, members) -> pd.DataFrame:
    return _cs_ls(px.pct_change(126), 21)


def build_mom002(px, tvol, members) -> pd.DataFrame:
    score = px.pct_change(126) / np.sqrt(tvol.rolling(21).mean())
    return _cs_ls(score, 21)


def build_mr001(px, vol, members) -> pd.DataFrame:
    return _cs_ls(-px.pct_change(21), 5)


def build_mr002(px, vol, members) -> pd.DataFrame:
    rsi = px.apply(lambda s: _rsi(s))
    sig = pd.DataFrame(np.where(rsi < 30, 1.0, np.where(rsi > 70, -1.0, np.nan)),
                       index=px.index, columns=px.columns)
    return _hold(sig, 5)


ASSET_CLASSES = {
    "forex": ["EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm",
              "USDCHFm", "NZDUSDm"],
    "metals": ["XAUUSDm", "XAGUSDm"],
    "indices": ["US500m", "US30m", "USTECm"],
    "crypto": ["BTCUSDm", "ETHUSDm"],
    "energy": ["USOILm"],
}


def build_mr003(px, vol, members) -> pd.DataFrame:
    assigned = set(sum(ASSET_CLASSES.values(), []))
    equities = [c for c in px.columns if c not in assigned]
    out = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    ret63 = px.pct_change(63)
    for syms in list(ASSET_CLASSES.values()) + [equities]:
        cols = [c for c in syms if c in px.columns]
        if len(cols) < 3:
            continue
        basket = ret63[cols].mean(axis=1)
        zs = ret63[cols].sub(basket, axis=0).apply(lambda s: _zscore(s, 63))
        sig = pd.DataFrame(np.where(zs < -2, 1.0, np.where(zs > 2, -1.0, np.nan)),
                           index=zs.index, columns=zs.columns)
        out[cols] = _hold(sig, 10)[cols]
    return out.fillna(0.0)


def build_brk001(px, vol, members) -> pd.DataFrame:
    is_high = px >= px.rolling(252, min_periods=126).max()
    exit_low = px < px.rolling(63, min_periods=32).min()
    raw = pd.DataFrame(np.where(is_high, 1.0, np.where(exit_low, 0.0, np.nan)),
                       index=px.index, columns=px.columns)
    return raw.ffill().fillna(0.0)


def build_brk002(px, vol, members) -> pd.DataFrame:
    atr = (px.rolling(14).max() - px.rolling(14).min()) / px
    rng = atr / atr.rolling(14).mean()
    expander = (_zscore(rng, 63) + 1.5) > 1.5 * rng.rank(pct=True)
    direction = np.sign(px.pct_change())
    return _hold(direction.where(expander & (rng > 1.2)), 5)


def build_vol001(px, vol, members) -> pd.DataFrame:
    return _cs_ls(-vol, 21)


def build_vol002(px, vol, members) -> pd.DataFrame:
    rets = px.pct_change()
    basket = rets.mean(axis=1)
    beta = rets.rolling(126, min_periods=60).cov(basket) / \
        basket.rolling(126, min_periods=60).var()
    return _cs_ls(-beta, 21)


def build_vol003(px, vol, members) -> pd.DataFrame:
    volofvol = vol.rolling(63).std()
    base = build_trend001(px, vol, members)
    lo = volofvol.quantile(0.25, axis=1)
    hi = volofvol.quantile(0.75, axis=1)
    scale = pd.DataFrame(
        np.where(volofvol.le(lo, axis=0), 1.0,
                 np.where(volofvol.ge(hi, axis=0), 0.0, np.nan)),
        index=px.index, columns=px.columns)
    return base * scale.ffill().fillna(1.0)


PAIRS_FROZEN = [("US500m", "USTECm"), ("XAUUSDm", "XAGUSDm"),
                ("EURUSDm", "GBPUSDm"), ("USOILm", "US500m"),
                ("BTCUSDm", "ETHUSDm")]


def _eg_z(a: pd.Series, b: pd.Series) -> float:
    m = pd.concat([np.log(a), np.log(b)], axis=1).dropna()
    if len(m) < 100 or m.std().min() == 0:
        return float("nan")
    beta = float(np.polyfit(m.iloc[:, 0], m.iloc[:, 1], 1)[0])
    spread = m.iloc[:, 1] - beta * m.iloc[:, 0]
    return float((spread.iloc[-1] - spread.mean()) /
                 (spread.std() if spread.std() else np.nan))


def _pair_positions(data, pairs) -> pd.DataFrame:
    """Trade the follower leg: long when spread z <= -2, short when >= +2,
    exit at |z| <= 0.5. Hedge ratio refit on trailing 126d window."""
    frames = []
    for lead, follower in pairs:
        if lead not in data or follower not in data:
            continue
        pa = data[lead]["close"]
        pb = data[follower]["close"]
        cal = pb.index
        pos = pd.Series(0.0, index=cal)
        state = 0.0
        for i in range(126, len(cal)):
            z = _eg_z(pa.iloc[i - 126:i], pb.iloc[i - 126:i])
            if not np.isnan(z):
                if state == 0.0 and z <= -2.0:
                    state = 1.0
                elif state == 0.0 and z >= 2.0:
                    state = -1.0
                elif state != 0.0 and abs(z) <= 0.5:
                    state = 0.0
            pos.iloc[i] = state
        frames.append(pos.rename(follower))
    if not frames:
        return pd.DataFrame(0.0, index=next(iter(data.values())).index,
                            columns=[])
    return pd.concat(frames, axis=1).fillna(0.0)


def build_sa001(px, vol, members, data=None) -> pd.DataFrame:
    return _pair_positions(data or {}, PAIRS_FROZEN)


def build_sa003(px, vol, members, data=None) -> pd.DataFrame:
    corr = px.pct_change().corr(min_periods=100)
    mask = np.triu(np.ones(corr.shape), 1).astype(bool)
    ranked = corr.abs().where(mask).stack().sort_values(ascending=False)
    used, pairs = set(), []
    for (a, b), rho in ranked.items():
        if rho < 0.80 or a in used or b in used:
            continue
        used.update({a, b})
        pairs.append((a, b))
        if len(pairs) >= 8:
            break
    return _pair_positions(data or {}, pairs)


def build_factor001(px, vol, members) -> pd.DataFrame:
    rets = px.pct_change()
    pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i in range(252, len(px.index) - 21, 21):
        win = rets.iloc[i - 252:i].dropna(axis=1, thresh=200).dropna()
        if win.shape[1] < 6:
            continue
        vals = np.linalg.eigh(win.corr().fillna(0.0).values)
        pc1 = pd.Series(vals[1][:, -1], index=win.columns)
        pc1 = pc1 / pc1.abs().sum()
        cols = [c for c in pc1.index if c in pos.columns]
        wts = pc1[cols].values
        trend_ok = (px[cols].iloc[i - 1] >
                    px[cols].iloc[i - 252]).reindex(cols).fillna(False)
        pos.loc[pos.index[i:i + 21], cols] = np.where(
            trend_ok.values, wts, 0.0)
    return pos


HYPOTHESES = [
    ("TREND-001", build_trend001),
    ("TREND-002", build_trend002),
    ("TREND-003", build_trend003),
    ("MOM-001", build_mom001),
    ("MOM-002", build_mom002),
    ("MR-001", build_mr001),
    ("MR-002", build_mr002),
    ("MR-003", build_mr003),
    ("BRK-001", build_brk001),
    ("BRK-002", build_brk002),
    ("VOL-001", build_vol001),
    ("VOL-002", build_vol002),
    ("VOL-003", build_vol003),
    ("SA-001", build_sa001),
    ("SA-003", build_sa003),
    ("FACTOR-001", build_factor001),
]


# -- Evaluation engine ------------------------------------------------------


def _sharpe(s):
    s = s.dropna()
    if len(s) < 60 or s.std() == 0:
        return 0.0
    return float(s.mean() / s.std() * np.sqrt(252))


def _maxdd(s):
    cum = (1 + s.fillna(0)).cumprod()
    return float(((cum - cum.cummax()) / cum.cummax()).min())


def _portfolio_series(px, pos, cost):
    """Equal-weight cross-section of per-flip-charged net daily returns."""
    rets = px.pct_change()
    p = pos.reindex(px.index).fillna(0.0)
    gross = (p.shift(1) * rets).mean(axis=1, skipna=True)
    turns = p.diff().abs().mean(axis=1, skipna=True).fillna(0.0)
    return gross - turns * cost


def _permutation_p(px, pos, n_permutations=500, seed=42):
    """Circular-shift null: destroys timing, preserves autocorrelation."""
    rng = np.random.default_rng(seed)
    rets = px.pct_change()
    base = pos.reindex(px.index).fillna(0.0)

    def _stat(offset):
        shifted = pd.DataFrame(np.roll(base.values, offset, axis=0),
                               index=base.index, columns=base.columns)
        gross = (shifted.shift(1) * rets).mean(axis=1, skipna=True)
        turns = shifted.diff().abs().mean(axis=1, skipna=True).fillna(0.0)
        return _sharpe(gross - turns * COST_ONE_WAY_BASE)

    observed = _stat(0)
    exceed = sum(
        1 for _ in range(n_permutations)
        if _stat(int(rng.integers(63, max(64, len(px) - 63)))) >= observed
    )
    return (exceed + 1) / (n_permutations + 1)


def evaluate_hypothesis(name, builder, data, px, vol, tvol, members):
    if name in ("SA-001", "SA-003"):
        pos = builder(px, vol, members, data=data)
    else:
        pos = builder(px, vol, members)
    pos = pos.reindex(columns=px.columns).fillna(0.0)
    if pos.abs().sum().sum() == 0:
        return {"hid": name, "verdict": "REJECTED",
                "reasons": ["no_signal"], "primary_failure": "no_signal"}

    net_b = _portfolio_series(px, pos, COST_ONE_WAY_BASE)
    net_a = _portfolio_series(px, pos, COST_ONE_WAY_ADVERSE)
    eq = ((1 + net_b).cumprod() * 100.0).tolist()

    wf = purged_walk_forward(eq, train_bars=WF_TRAIN, test_bars=WF_TEST,
                             purge_bars=WF_PURGE, embargo_bars=WF_EMBARGO)
    wf_cons = wf.pct_profitable_windows / 100.0

    yearly = net_b.groupby(net_b.index.year).sum()
    pct_pos_years = float((yearly > 0).mean()) if len(yearly) else 0.0

    per_sym = {}
    exposed = []
    for sym in px.columns:
        if pos[sym].abs().sum() <= 20:
            continue
        sub_px = px[[sym]].rename(columns={sym: "close"})
        r = bt_net(sub_px, pos[sym], hp=1, cost_one_way=COST_ONE_WAY_BASE,
                   bars_per_trading_day=1)
        per_sym[sym] = round(r.net_sharpe, 4)
        exposed.append(r.net_sharpe)
    breadth = float(np.mean([s > 0 for s in exposed])) if exposed else 0.0

    p_raw = _permutation_p(px, pos)
    reasons = []
    if _sharpe(net_b) < GATES["net_sharpe_min"]:
        reasons.append("net_sharpe_below_gate")
    if _sharpe(net_a) < GATES["net_sharpe_adverse_min"]:
        reasons.append("adverse_cost_below_gate")
    if _maxdd(net_b) <= GATES["max_dd_limit"]:
        reasons.append("catastrophic_dd")
    if wf_cons < GATES["wf_consistency_min"]:
        reasons.append("wf_inconsistent")
    if pct_pos_years < GATES["pct_positive_years_min"]:
        reasons.append("year_dependence")
    if breadth < 0.30 and exposed:
        reasons.append("instrument_dependent")
    if p_raw * FAMILY_SIZE > FAMILY_P_MAX:
        reasons.append("family_permutation_insignificant")

    verdict = "SUPPORTED" if not reasons else (
        "REJECTED" if len(reasons) >= 2 or "no_signal" in reasons else "FRAGILE")
    p_cum = min(1.0, p_raw * CUMULATIVE_TRIALS)
    if verdict == "SUPPORTED" and p_cum > 0.05:
        verdict = "FRAGILE"
        reasons.append("cumulative_trial_weakness")

    dsr = None
    if verdict == "SUPPORTED":
        d = deflated_sharpe_ratio(
            observed_sharpe=_sharpe(net_b), n_trials=CUMULATIVE_TRIALS,
            returns=list(net_b.dropna()), trial_sr_std=0.5,
            confidence=0.95)
        dsr = d.to_dict()
        if not d.significant:
            verdict = "FRAGILE"
            reasons.append("dsr_not_significant")

    return {
        "hid": name, "verdict": verdict, "reasons": reasons,
        "primary_failure": reasons[0] if reasons else "",
        "gross_sharpe": round(_sharpe(_portfolio_series(px, pos, 0.0)), 4),
        "net_sharpe": round(_sharpe(net_b), 4),
        "net_sharpe_adverse": round(_sharpe(net_a), 4),
        "max_dd": round(_maxdd(net_b), 4),
        "wf_consistency": round(wf_cons, 4),
        "wf_windows": wf.total_windows,
        "degradation": round(abs(wf.degradation_ratio), 3),
        "pct_positive_years": round(pct_pos_years, 3),
        "instrument_breadth": round(breadth, 3),
        "n_flips": int(pos.diff().abs().sum().sum()),
        "p_raw": round(p_raw, 4),
        "p_family": round(min(1.0, p_raw * FAMILY_SIZE), 4),
        "p_cumulative": round(p_cum, 4),
        "dsr": dsr,
        "per_instrument_net_sharpe": per_sym,
    }


def run(data_dir: str = DATA_DIR):
    assert verify_snapshot(data_dir), "frozen snapshot mismatch — aborting"
    data = load_snapshot(data_dir)
    members = build_membership(data)
    px = member_frame(data, "close")
    vol = px.pct_change().rolling(63).std()
    tvol = member_frame(data, "tick_volume") if "tick_volume" in \
        next(iter(data.values())).columns else vol * 0 + 1

    results = []
    for name, builder in HYPOTHESES:
        print(f"[R5] {name} ...", flush=True)
        results.append(evaluate_hypothesis(name, builder, data, px, vol,
                                           tvol, members))
    print("\n[R5] family:", FAMILY_SIZE, "| cumulative:", CUMULATIVE_TRIALS)
    dist = Counter(r["verdict"] for r in results)
    print("[R5] verdicts:", dict(dist))
    return results


def write_reports(results):
    os.makedirs("reports", exist_ok=True)
    with open(REPORT_JSON, "w") as f:
        json.dump({
            "campaign": "R5_SWING_BREADTH",
            "preregistration": "research/campaigns/R5_SWING_BREADTH_PREREGISTRATION.md",
            "data_manifest_sha256_prefix": "3d10cf9322bda6cd9f5d4966a53e4d8d",
            "prior_evaluations": PRIOR_EVALUATIONS,
            "family_size": FAMILY_SIZE,
            "cumulative_trials": CUMULATIVE_TRIALS,
            "results": results,
        }, f, indent=2, sort_keys=True)

    lines = [
        "# CAMPAIGN R5 - SWING BREADTH (pre-registered)", "",
        "**Snapshot:** R5_SWING_BREADTH_D1 (38 instruments, frozen)",
        f"**Family:** {FAMILY_SIZE} Bonferroni | **Cumulative:** {CUMULATIVE_TRIALS} trials",
        "**Costs:** corrected per-flip accounting (7.5 / 12.5 bps one-way)", "",
        "## VERDICTS", "",
        "| ID | Net | Adv | DD | WF | Years+ | Breadth | p_raw | p_fam | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda x: x.get("net_sharpe", 0), reverse=True):
        lines.append(
            f"| {r['hid']} | {r.get('net_sharpe', 0):+.2f} | "
            f"{r.get('net_sharpe_adverse', 0):+.2f} | {r.get('max_dd', 0):.1%} | "
            f"{r.get('wf_consistency', 0):.0%} | {r.get('pct_positive_years', 0):.0%} | "
            f"{r.get('instrument_breadth', 0):.0%} | {r.get('p_raw', 1):.3f} | "
            f"{r.get('p_family', 1):.3f} | **{r['verdict']}** |")
    surv = [r["hid"] for r in results if r["verdict"] == "SUPPORTED"]
    lines += ["", f"**Survivors: {len(surv)}/{len(results)}**"]
    if not surv:
        lines += ["", "**DECISION:** zero survivors under the pre-registered gates. "
                      "Per R5 decision rule: null evidence recorded; library statuses "
                      "move to REJECTED; next attempt requires a new pre-registration."]
    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n[R5] reports written: {REPORT_MD}, {REPORT_JSON}")


if __name__ == "__main__":
    res = run()
    write_reports(res)
