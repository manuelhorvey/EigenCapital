"""Phases 8-9 — Counterfactual protection experiments (offline, preregistered).

Trial families and acceptance criteria are preregistered in
reports/r4_economics_audit/trial_ledger.json (written BEFORE this run).
Control = frozen R4 exits. Every trial is reported, including failures.

Outputs:
  reports/r4_economics_audit/counterfactual_results.json
  reports/r4_economics_audit/curve_<trial_id>.csv  (selected variants)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports" / "r4_economics_audit"
sys.path.insert(0, str(REPO / "scripts" / "audit"))
sys.path.insert(0, str(REPO / "src"))

import reconstruct as rec  # noqa: E402

from eigencapital.config import load_config  # noqa: E402

COST_BPS = 10.0


def load_context():
    config = load_config("production")
    allowed = dict(config.broker.allowed_symbols)
    frames, _ = rec.build_universe(allowed)
    signal_syms = [s for s in sorted(frames) if s in allowed]
    cw = pd.DataFrame({s: frames[s]["close"] for s in signal_syms}).sort_index()
    hw = pd.DataFrame({s: frames[s]["high"] for s in signal_syms}).reindex(cw.index)
    lw = pd.DataFrame({s: frames[s]["low"] for s in signal_syms}).reindex(cw.index)

    # per-symbol-calendar ATR14% wide (same method as analyses.py)
    atr_rows = {}
    for s in signal_syms:
        f = frames[s]
        pc = f["close"].shift(1)
        tr = pd.concat(
            [f["high"] - f["low"], (f["high"] - pc).abs(), (f["low"] - pc).abs()],
            axis=1,
        ).max(axis=1)
        atr_rows[s] = tr.rolling(14, min_periods=10).mean() / f["close"]
    atr = pd.DataFrame(atr_rows).reindex(cw.index)

    fin, regime_on = rec.replicate_signal(cw)
    eligible = [s for s, cls in allowed.items() if not cls.endswith("_excluded")]

    trades = pd.read_parquet(OUT / "trades_enriched.parquet")
    trades["entry_ts"] = pd.to_datetime(trades["entry_ts"])
    trades["exit_ts"] = pd.to_datetime(trades["exit_ts"])
    return dict(
        config=config,
        allowed=allowed,
        frames=frames,
        cw=cw,
        hw=hw,
        lw=lw,
        atr=atr,
        fin=fin,
        regime_on=regime_on,
        eligible=eligible,
        trades=trades,
    )


def walk_episode(row, ctx, params) -> tuple[pd.Timestamp | None, float | None, str]:
    """Return (exit_date, exit_price, exit_type) under variant params.
    Pessimistic same-bar order: stop -> trail -> TP."""
    if row["exit_reason"] == "end_of_data":
        natural_end = ctx["cw"].index[-1]
    else:
        natural_end = row["exit_ts"]
    sym = row["symbol"]
    d = 1 if row["direction"] == "LONG" else -1
    entry_px = row["entry_price"]
    R_abs = row["atr14pct_at_entry"] * entry_px if np.isfinite(row["atr14pct_at_entry"]) else np.nan

    stop_px: float | None = None
    tp_px: float | None = None
    trail_dist: float | None = None
    if "stop_pct" in params:
        stop_px = entry_px * (1 - d * params["stop_pct"])
    elif "atr_mult" in params and np.isfinite(R_abs):
        stop_px = entry_px - d * params["atr_mult"] * R_abs
    if "tp_R" in params and np.isfinite(R_abs):
        tp_px = entry_px + d * params["tp_R"] * R_abs
    if "trail_pct" in params:
        trail_pct = params["trail_pct"]
    elif "trail_atr" in params and np.isfinite(R_abs):
        trail_dist = params["trail_atr"] * R_abs
        trail_pct = None
    else:
        trail_pct = None
    giveback = params.get("mfe_giveback_frac")
    loser_bars = params.get("loser_exit_bars")
    timecap = params.get("max_hold_days")

    idx = ctx["cw"].index
    try:
        e_loc = idx.get_loc(row["entry_ts"])
        n_loc = idx.get_loc(natural_end)
    except KeyError:
        return None, None, "natural"
    o = ctx["frames"][sym]["open"].reindex(idx).to_numpy()
    h = ctx["hw"][sym].to_numpy()
    lo_ = ctx["lw"][sym].to_numpy()
    c = ctx["cw"][sym].to_numpy()

    peak_close = entry_px
    mfe_close = 0.0
    trail_px = None
    bars = 0
    for i in range(e_loc + 1, n_loc + 1):
        bars += 1
        oi, hi, li, ci = o[i], h[i], lo_[i], c[i]
        if not (np.isfinite(oi) and np.isfinite(hi) and np.isfinite(li) and np.isfinite(ci)):
            continue
        # ratchet trail before checks (prior-close basis)
        dist: float | None = None
        if trail_pct is not None:
            dist = trail_pct * peak_close
        elif trail_dist is not None:
            dist = trail_dist
        if dist is not None:
            cand = peak_close - d * dist
            trail_px = cand if trail_px is None else (max(trail_px, cand) if d > 0 else min(trail_px, cand))
        # 1) hard stop (pessimistic first)
        if stop_px is not None and ((d > 0 and li <= stop_px) or (d < 0 and hi >= stop_px)):
            fill = oi if (d > 0 and oi < stop_px) or (d < 0 and oi > stop_px) else stop_px
            return idx[i], float(fill), "stop"
        # 2) trail
        if trail_px is not None and ((d > 0 and li <= trail_px) or (d < 0 and hi >= trail_px)):
            fill = oi if (d > 0 and oi < trail_px) or (d < 0 and oi > trail_px) else trail_px
            return idx[i], float(fill), "trail"
        # 3) TP
        if tp_px is not None and ((d > 0 and hi >= tp_px) or (d < 0 and li <= tp_px)):
            fill = oi if (d > 0 and oi > tp_px) or (d < 0 and oi < tp_px) else tp_px
            return idx[i], float(fill), "tp"
        # 4) MFE giveback on closes
        if giveback is not None:
            fav = d * (ci / entry_px - 1.0)
            mfe_close = max(mfe_close, fav)
            if mfe_close > 0 and fav <= mfe_close * (1 - giveback):
                return idx[i], float(ci), "giveback"
        # 5) loser time-stop / cap
        ret_now = d * (ci / entry_px - 1.0)
        if loser_bars is not None and bars >= loser_bars and ret_now < 0:
            return idx[i], float(ci), "time_loser"
        if timecap is not None and bars >= timecap:
            return idx[i], float(ci), "time_cap"
        peak_close = max(peak_close, ci) if d > 0 else min(peak_close, ci)
    return None, None, "natural"


def policy_exit_dates(ctx) -> dict[str, pd.Series]:
    """Per-symbol daily boolean exit flags for policy variants."""
    fin, regime_on, eligible = ctx["fin"], ctx["regime_on"], ctx["eligible"]
    w_elig = fin[eligible]
    # daily rank of |w| among active eligibles (1 = strongest)
    absr = w_elig.abs().where(w_elig.abs() > 0.005)
    rank_df = absr.rank(axis=1, ascending=False)
    regime_off = ~regime_on.reindex(fin.index).fillna(False)
    return {"regime_off": regime_off, "rank_worse_16": (rank_df > 16)}


def episode_return(row, exit_date, exit_price, cost_side=COST_BPS) -> float:
    d = 1 if row["direction"] == "LONG" else -1
    px = exit_price if exit_price is not None else row["exit_price"]
    gross = d * (px / row["entry_price"] - 1.0)
    return gross - 2 * cost_side / 1e4


def portfolio_curve(trades_with_exits: pd.DataFrame, ctx, label="") -> pd.Series:
    """Daily portfolio net returns from frozen-weight episodes with variant exits."""
    cw, dates = ctx["cw"], ctx["cw"].index
    W = pd.DataFrame(0.0, index=dates, columns=cw.columns)
    rets = cw.pct_change()
    for _, r in trades_with_exits.iterrows():
        s = r["symbol"]
        if s not in W.columns:
            continue
        mask = (dates >= r["entry_ts"]) & (dates <= r["_exit_ts_final"])
        W.loc[mask, s] = r["signal_strength_entry"]
    turnover = W.diff().abs().sum(axis=1).fillna(0.0)
    gross = (W.shift(1).fillna(0.0) * rets.fillna(0.0)).sum(axis=1)
    net = gross - turnover * COST_BPS / 1e4
    net.attrs["label"] = label
    return net


def metrics(daily_ret: pd.Series, episodes: pd.DataFrame, control_episodes=None) -> dict:
    r = daily_ret.dropna()
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    downside = r[r < 0].std() * np.sqrt(252)
    wins = episodes[episodes["_ret"] > 0]["_ret"].sum()
    losses = -episodes[episodes["_ret"] < 0]["_ret"].sum()
    years = {}
    for y, g in r.groupby(r.index.year):
        sd = g.std() * np.sqrt(252)
        years[int(y)] = float(g.mean() * 252 / sd) if sd > 0 else 0.0
    stopped = episodes[episodes["_etype"].isin(["stop", "trail", "time_loser", "time_cap", "giveback"])]
    false_stop = None
    if control_episodes is not None and len(stopped):
        ctrl = control_episodes["_ret"]
        common = [t for t in stopped.index if t in ctrl.index]
        false_stop = float(np.mean([ctrl[t] > 0 for t in common])) if common else None
    return {
        "ann_return": float(r.mean() * 252),
        "ann_vol": float(r.std() * np.sqrt(252)),
        "sharpe": float(r.mean() * 252 / (r.std() * np.sqrt(252))) if r.std() > 0 else 0.0,
        "sortino": float(r.mean() * 252 / downside) if downside and downside > 0 else None,
        "max_drawdown": float(dd.min()),
        "calmar": float(r.mean() * 252 / abs(dd.min())) if dd.min() < 0 else None,
        "profit_factor": float(wins / losses) if losses > 0 else None,
        "win_rate_trades": float((episodes["_ret"] > 0).mean()),
        "n_trades": len(episodes),
        "avg_trade_net": float(episodes["_ret"].mean()),
        "tail_daily_P05": float(r.quantile(0.05)),
        "cvar95_daily": float(r[r <= r.quantile(0.05)].mean()),
        "yearly_sharpe": years,
        "yearly_consistency": float(np.mean([v > 0 for v in years.values()])) if years else None,
        "sharpe_first_half": None,  # filled below
        "stopped_n": len(stopped),
        "stop_frequency": float(len(stopped) / max(len(episodes), 1)),
        "false_stop_rate": false_stop,
        "half_split": {},
    }


def block_bootstrap_p(diff: pd.Series, n_boot=2000, block=20, seed=3) -> float:
    """One-sided p-value that mean(diff) > 0 via moving-block bootstrap."""
    x = diff.dropna().to_numpy()
    if len(x) < 100 or np.allclose(x, 0):
        return float("nan")
    rng = np.random.default_rng(seed)
    nb = len(x) // block
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, len(x) - block, size=nb)
        sample = np.concatenate([x[s : s + block] for s in starts])
        means[b] = sample[: len(x)].mean()
    p = float((means <= 0).mean())
    return max(min(p, 1.0), 1.0 / n_boot)


def main() -> None:
    ledger = json.loads((OUT / "trial_ledger.json").read_text())
    ctx = load_context()
    trades = ctx["trades"]
    pol = policy_exit_dates(ctx)

    results: dict = {"control": None, "trials": [], "h1_sensitivity": None}

    # ── Control ────────────────────────────────────────────────────
    t_ctrl = trades.copy()
    t_ctrl["_exit_ts_final"] = t_ctrl["exit_ts"]
    t_ctrl["_ret"] = t_ctrl["net_return_10bps_side"]
    t_ctrl["_etype"] = "natural"
    curve_ctrl = portfolio_curve(t_ctrl, ctx, "control")
    m_ctrl = metrics(curve_ctrl, t_ctrl)
    halves = np.array_split(curve_ctrl.index.unique(), 2)
    m_ctrl["half_split"] = {
        str(i): float(curve_ctrl.loc[h].mean() * 252 / (curve_ctrl.loc[h].std() * np.sqrt(252)))
        for i, h in enumerate(halves)
    }
    results["control"] = {"id": "baseline", **m_ctrl}
    print(
        f"control sharpe={m_ctrl['sharpe']:.3f} ann={m_ctrl['ann_return']:+.4f} "
        f"maxdd={m_ctrl['max_drawdown']:.3f} pf={m_ctrl['profit_factor']}"
    )

    curves = {"control": curve_ctrl}
    ep_sets = {"control": t_ctrl}

    # ── Trials ─────────────────────────────────────────────────────
    for fam in ledger["families"]:
        if fam["family_id"] == "F0":
            continue
        for tr in fam["trials"]:
            tid = tr["id"]
            params = tr["param"]
            exits: list[dict] = []
            for _, row in trades.iterrows():
                xd, xp, etype = None, None, "natural"
                if any(
                    k in params
                    for k in (
                        "stop_pct",
                        "atr_mult",
                        "tp_R",
                        "trail_pct",
                        "trail_atr",
                        "mfe_giveback_frac",
                        "loser_exit_bars",
                        "max_hold_days",
                    )
                ):
                    xd, xp, etype = walk_episode(row, ctx, params)
                elif params.get("exit_on_regime_off"):
                    off_days = pol["regime_off"]
                    window = off_days.loc[(off_days.index > row["entry_ts"]) & (off_days.index <= row["exit_ts"])]
                    if window.any():
                        xd = window.index[0]
                        xp = float(ctx["cw"][row["symbol"]].asof(xd))
                        etype = "regime_off"
                elif "exit_rank_worse_than" in params:
                    flag = pol["rank_worse_16"]
                    window = flag.loc[row["symbol"]] if False else None
                    col = flag.get(row["symbol"])
                    if col is not None:
                        win = col.loc[(col.index > row["entry_ts"]) & (col.index <= row["exit_ts"])]
                        hit = win[win.astype(bool)]
                        if len(hit):
                            xd = hit.index[0]
                            xp = float(ctx["cw"][row["symbol"]].asof(xd))
                            etype = "rank_decay"
                final_d = xd if xd is not None else row["exit_ts"]
                final_p = xp if xp is not None else row["exit_price"]
                exits.append(
                    {
                        "trade_id": row.name,
                        "symbol": row["symbol"],
                        "_exit_ts_final": final_d,
                        "_exit_px": final_p,
                        "_etype": etype,
                    }
                )
            ex = pd.DataFrame(exits).set_index("trade_id")
            tv = trades.copy()
            tv["_exit_ts_final"] = ex["_exit_ts_final"]
            tv["_etype"] = ex["_etype"]
            tv["_ret"] = [
                episode_return(row, ex.loc[i, "_exit_ts_final"], ex.loc[i, "_exit_px"]) for i, row in tv.iterrows()
            ]
            cv = portfolio_curve(tv, ctx, tid)
            mv = metrics(cv, tv, control_episodes=t_ctrl)
            halves = np.array_split(cv.index.unique(), 2)
            mv["half_split"] = {
                str(i): float(cv.loc[h].mean() * 252 / (cv.loc[h].std() * np.sqrt(252))) for i, h in enumerate(halves)
            }
            diff = cv - curve_ctrl
            p_raw = block_bootstrap_p(diff)
            fam_size = next(f["n_trials"] for f in ledger["families"] if f["family_id"] == fam["family_id"])
            mv.update(
                {
                    "trial_id": tid,
                    "family": fam["family_id"],
                    "params": params,
                    "sharpe_delta_vs_control": mv["sharpe"] - m_ctrl["sharpe"],
                    "maxdd_delta_vs_control": mv["max_drawdown"] - m_ctrl["max_drawdown"],
                    "bootstrap_p_raw": p_raw,
                    "bonferroni_p": min(1.0, p_raw * fam_size) if np.isfinite(p_raw) else None,
                }
            )
            results["trials"].append(mv)
            curves[tid] = cv
            ep_sets[tid] = tv
            print(
                f"{tid:28s} sharpe={mv['sharpe']:+.3f} Δ={mv['sharpe_delta_vs_control']:+.3f} "
                f"maxdd={mv['max_drawdown']:+.3f} stops={mv['stopped_n']:4d} "
                f"false_stop={mv['false_stop_rate'] if mv['false_stop_rate'] is not None else '—'} "
                f"p_bonf={mv['bonferroni_p']}"
            )

    # ── H1-refined sensitivity (subset where H1 exists) ────────────
    h1_syms = ["AUDUSD", "EURUSD", "GBPUSD"]
    h1_frames = {}
    for s in h1_syms:
        p = REPO / "data" / "intraday_h1" / f"{s}m_H1.csv"
        if p.exists():
            df = pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()
            h1_frames[s] = df[~df.index.duplicated(keep="last")]
    sens = []
    if h1_frames:
        for tid in ["F2_atr_1", "F2_atr_2", "F1_stop_1pct", "F1_stop_2pct"]:
            trig_d1 = trig_h1 = same = tot = 0
            for _, row in trades.iterrows():
                if row["symbol"] not in h1_frames:
                    continue
                params = next(
                    t["param"]
                    for f in ledger["families"]
                    if f["family_id"] == "F1" or f["family_id"] == "F2"
                    for t in f["trials"]
                    if t["id"] == tid
                )
                d1 = walk_episode(row, ctx, params)
                # H1 walk
                f1 = h1_frames[row["symbol"]]
                try:
                    ei = f1.index.searchsorted(row["entry_ts"])
                    ni = f1.index.searchsorted(row["exit_ts"])
                except Exception:
                    continue
                d = 1 if row["direction"] == "LONG" else -1
                R_abs = row["atr14pct_at_entry"] * row["entry_price"]
                stop = (
                    row["entry_price"]
                    - d
                    * params.get(
                        "atr_mult",
                        params.get("stop_pct", 0) / row["atr14pct_at_entry"]
                        if np.isfinite(row["atr14pct_at_entry"]) and row["atr14pct_at_entry"] > 0
                        else 1,
                    )
                    * R_abs
                    if "atr_mult" in params
                    else row["entry_price"] * (1 - d * params["stop_pct"])
                )
                hh, ll = f1["high"].to_numpy(), f1["low"].to_numpy()
                trig_h1_date = None
                for i in range(ei + 1, min(ni + 1, len(f1))):
                    if (d > 0 and ll[i] <= stop) or (d < 0 and hh[i] >= stop):
                        trig_h1_date = f1.index[i]
                        break
                tot += 1
                td1 = d1[0] if d1 and d1[0] is not None and d1[2] == "stop" else None
                if td1 is not None and trig_h1_date is not None:
                    same += int(td1.date() == trig_h1_date.date())
                    trig_d1 += 1
                    trig_h1 += 1
                elif td1 is not None:
                    trig_d1 += 1
                elif trig_h1_date is not None:
                    trig_h1 += 1
            sens.append(
                {
                    "trial": tid,
                    "episodes_in_subset": tot,
                    "stops_triggered_D1": trig_d1,
                    "stops_triggered_H1": trig_h1,
                    "trigger_day_agreement": round(same / max(trig_d1, 1), 3),
                }
            )
    results["h1_sensitivity"] = sens

    (OUT / "counterfactual_results.json").write_text(json.dumps(results, indent=2, default=str))

    # save a few curves
    for tid in [
        "control",
        "F2_atr_2",
        "F2_atr_3",
        "F6_regimeoff_flatten",
        "F7_timecap_60d",
    ]:
        if tid in curves:
            curves[tid].rename("port_net").to_csv(OUT / f"curve_{tid}.csv")
    print("\nwrote counterfactual_results.json")


if __name__ == "__main__":
    main()
