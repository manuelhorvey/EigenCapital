#!/usr/bin/env python3
"""Trade win/loss rate and duration analysis for QuantForge."""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.builder import build_features, compute_macro_derived
from backtests import compute_per_fold_labels
from features.registry import FEATURE_REGISTRY
from shared.volatility import compute_atr_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quantforge.trade_analysis")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SLTP_CFG = {
    "GC":     {"sl": 1.00, "tp": 4.00},
    "USDCHF": {"sl": 0.85, "tp": 3.00},
    "AUDCHF": {"sl": 2.75, "tp": 3.50},
    "USDCAD": {"sl": 2.50, "tp": 2.00},
    "ES":     {"sl": 2.00, "tp": 5.50},
    "NQ":     {"sl": 2.50, "tp": 5.00},
    "GBPCAD": {"sl": 2.50, "tp": 2.50},
    "GBPNZD": {"sl": 3.00, "tp": 1.00},
    "NZDCAD": {"sl": 2.50, "tp": 4.00},
    "DJI":    {"sl": 0.50, "tp": 4.00},
    # New additions (candidate sweep 2026-06)
    "EURUSD": {"sl": 3.00, "tp": 1.50},
    "NZDUSD": {"sl": 2.50, "tp": 1.50},
    # New additions (filter sweep 2026-06)
    "GBPAUD": {"sl": 1.00, "tp": 2.00},
    "NZDCHF": {"sl": 1.00, "tp": 4.00},
    "CADCHF": {"sl": 1.00, "tp": 4.00},
    "AUDUSD": {"sl": 1.50, "tp": 4.00},
    "AUDNZD": {"sl": 2.00, "tp": 1.00},
    # New additions (remaining filter 2026-06)
    "EURCHF": {"sl": 1.00, "tp": 3.00},
    "EURCAD": {"sl": 1.00, "tp": 1.00},
    "EURNZD": {"sl": 1.50, "tp": 2.50},
    "GBPCHF": {"sl": 1.00, "tp": 2.00},
}
DASHBOARD_TICKERS = {
    "GC=F": "GC",
    "USDCHF=X": "USDCHF", "AUDCHF=X": "AUDCHF",
    "USDCAD=X": "USDCAD", "ES=F": "ES",
    "NQ=F": "NQ", "GBPCAD=X": "GBPCAD", "GBPNZD=X": "GBPNZD",
    "NZDCAD=X": "NZDCAD", "^DJI": "DJI",
    # New additions (candidate sweep 2026-06)
    "EURUSD=X": "EURUSD", "NZDUSD=X": "NZDUSD",
    # New additions (filter sweep 2026-06)
    "GBPAUD=X": "GBPAUD", "NZDCHF=X": "NZDCHF",
    "CADCHF=X": "CADCHF", "AUDUSD=X": "AUDUSD",
    "AUDNZD=X": "AUDNZD",
    # New additions (remaining filter 2026-06)
    "EURCHF=X": "EURCHF", "EURCAD=X": "EURCAD",
    "EURNZD=X": "EURNZD", "GBPCHF=X": "GBPCHF",
}
MODEL_DEPTH = {
    "GC": 2, "USDCHF": 4,
    "AUDCHF": 2, "USDCAD": 5, "ES": 2,
    "NQ": 2, "GBPCAD": 2, "GBPNZD": 3, "NZDCAD": 2, "DJI": 4,
    # New additions (candidate sweep 2026-06)
    "EURUSD": 3, "NZDUSD": 5,
    # New additions (filter sweep 2026-06)
    "GBPAUD": 2, "NZDCHF": 2,
    "CADCHF": 2, "AUDUSD": 2,
    "AUDNZD": 2,
    # New additions (remaining filter 2026-06)
    "EURCHF": 4, "EURCAD": 3,
    "EURNZD": 3, "GBPCHF": 2,
}

DEF_SL, DEF_TP = 1.0, 2.0
MAX_BARS, THR = 60, 0.45
CONFIRM = 2

# Volatility regime geometry — mimics paper_trading.yaml regime_geometry
# LOW/MID/HIGH vol mapped to GREEN/YELLOW/RED behavior
REGIME_GEOM = {
    "low":  {"sl": 0.80, "tp": 1.10},
    "mid":  {"sl": 1.00, "tp": 1.00},
    "high": {"sl": 1.00, "tp": 1.00},
}  # min bars before allowing signal flip


def analyze_paper_trades() -> list[dict]:
    db = os.path.join(BASE, "data", "live", "state.db")
    if not os.path.exists(db):
        return []
    import sqlite3
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def paper_stats(trades: list[dict]) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    rc = "reason" if "reason" in df.columns else "exit_reason"
    rtc = "return" if "return" in df.columns else "pnl"
    bc = "bars" if "bars" in df.columns else "bars_held"
    df[rc] = df[rc].astype(str).str.lower().str.replace("_hit", "")
    s = {"n_trades": len(df)}
    s["win_rate"] = float((df[rtc] > 0).mean())
    s["loss_rate"] = float((df[rtc] < 0).mean())
    s["tp_rate"] = float((df[rc] == "tp").mean())
    s["sl_rate"] = float((df[rc] == "sl").mean())
    s["flip_rate"] = float((df[rc] == "signal_flip").mean())
    s["avg_return"] = float(df[rtc].mean())
    s["avg_bars"] = float(df[bc].mean())
    ba = {}
    for a, g in df.groupby("asset"):
        ba[a] = {"n": len(g), "win_rate": float((g[rtc] > 0).mean()), "avg_bars": float(g[bc].mean()),
                 "tp_rate": float((g[rc] == "tp").mean()), "sl_rate": float((g[rc] == "sl").mean())}
    s["by_asset"] = ba
    return s


def fetch_ohlcv(ticker: str, years: int = 10) -> pd.DataFrame:
    import yfinance as yf
    safe = ticker.replace("=", "_").replace("-", "_").replace("^", "")
    path = os.path.join(BASE, "data", "raw", f"{safe}_1d.parquet")
    if os.path.exists(path):
        df = pd.read_parquet(path)
        if isinstance(df.index, pd.DatetimeIndex) and len(df) > 100:
            if df.index.tz is None:
                df.index = df.index.tz_localize("US/Eastern")
            else:
                df.index = df.index.tz_convert("US/Eastern")
            return df
    end = pd.Timestamp.now()
    df = yf.download(ticker, start=f"{end.year - years}-01-01", end=end.strftime("%Y-%m-%d"),
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Open": "open", "Volume": "volume"})
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("US/Eastern")
    else:
        df.index = df.index.tz_convert("US/Eastern")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path)
    return df


def load_macro() -> pd.DataFrame:
    m = pd.read_parquet(os.path.join(BASE, "data", "processed", "macro_factors.parquet"))
    return compute_macro_derived(m)


def _signals(proba: np.ndarray, idx: pd.Index, thr: float | None = None) -> pd.DataFrame:
    thr = THR if thr is None else thr
    s = pd.Series(1, index=idx, dtype=int)
    s[proba[:, 2] > thr] = 2
    s[proba[:, 0] > thr] = 0
    c = (proba[:, 2] > thr) & (proba[:, 0] > thr)
    if c.any():
        s[c] = np.where(proba[c, 2] >= proba[c, 0], 2, 0)
    return pd.DataFrame({"signal": s, "pl": proba[:, 2], "ps": proba[:, 0]}, index=idx)


def _simulate(sigs: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series,
              name: str, slm: float, tpm: float, atr: pd.Series,
              regime: pd.Series | None = None) -> list[dict]:
    trades = []
    in_pos = False
    pos = entry_px = sl = tp = 0.0
    entry_i = -1
    entry_sig = 0
    entry_dt = None
    hi_water = lo_water = 0.0
    for i in range(1, len(sigs)):
        cs = sigs["signal"].iloc[i]
        cc, ch, cl = float(close.iloc[i]), float(high.iloc[i]), float(low.iloc[i])
        dt = str(sigs.index[i].date())
        if in_pos:
            hi_water = max(hi_water, ch)
            lo_water = min(lo_water, cl)
            sl_hit = (pos == 2 and cl <= sl) or (pos == 0 and ch >= sl)
            tp_hit = (pos == 2 and ch >= tp) or (pos == 0 and cl <= tp)
            held = i - entry_i
            flip = cs != 1 and cs != entry_sig
            reason = None
            if sl_hit:
                reason = "sl"
                ep = sl
            elif tp_hit:
                reason = "tp"
                ep = tp
            elif flip:
                reason = "signal_flip"
                ep = cc
            elif held >= MAX_BARS:
                reason = "time_stop"
                ep = cc
            if reason:
                ret = (ep / entry_px - 1) if pos == 2 else (entry_px / ep - 1)
                risk = abs(entry_px - sl) / entry_px if sl > 0 else 0.01
                if pos == 2:
                    mae_r = (entry_px - lo_water) / (entry_px * risk) if risk else 0.0
                    mfe_r = (hi_water - entry_px) / (entry_px * risk) if risk else 0.0
                else:
                    mae_r = (hi_water - entry_px) / (entry_px * risk) if risk else 0.0
                    mfe_r = (entry_px - lo_water) / (entry_px * risk) if risk else 0.0
                trades.append({"asset": name, "side": "long" if pos == 2 else "short",
                               "entry_price": round(entry_px, 6), "entry_date": str(entry_dt.date()),
                               "exit_price": round(ep, 6), "exit_date": dt, "exit_reason": reason,
                               "bars_held": held, "return": round(ret, 6),
                               "r_multiple": round(ret / risk, 4) if risk else 0.0,
                               "mae_r": round(mae_r, 4), "mfe_r": round(mfe_r, 4),
                               "entry_regime": rg})
                in_pos = False
                continue
        if not in_pos and cs != 1:
            in_pos = True
            pos = cs
            entry_sig = cs
            entry_px = cc
            entry_i = i
            entry_dt = sigs.index[i]
            v = max(float(atr.iloc[i]) if i < len(atr) else 0.01, 0.001)
            rg = regime.iloc[i] if regime is not None else "mid"
            rg_sl = REGIME_GEOM.get(rg, {}).get("sl", 1.0)
            rg_tp = REGIME_GEOM.get(rg, {}).get("tp", 1.0)
            sl = entry_px * (1 - v * slm * rg_sl) if pos == 2 else entry_px * (1 + v * slm * rg_sl)
            tp = entry_px * (1 + v * tpm * rg_tp) if pos == 2 else entry_px * (1 - v * tpm * rg_tp)
            hi_water = ch
            lo_water = cl
    return trades


def backtest_asset(ticker: str, macro: pd.DataFrame, ref: pd.DataFrame | None, years: int = 3) -> list[dict]:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    contract = FEATURE_REGISTRY.get(ticker)
    if not contract:
        return []
    name = contract.name
    logger.info("  %s (%s)", ticker, name)
    df = fetch_ohlcv(ticker)
    if len(df) < 200:
        logger.warning("    insufficient data")
        return []
    try:
        fdf = build_features(df, macro, ref, contract, compute_labels=False)
    except Exception as e:
        logger.warning("    features failed: %s", e)
        return []
    X = fdf[list(contract.features)]
    close, high, low = [c.reindex(X.index).ffill() for c in [df["close"], df["high"], df["low"]]]
    if len(X) < 200:
        return []
    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    # Volatility regime: low/mid/high from ATR percentile ranks
    atr_pct = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
    regime_map = {0: "low", 1: "mid", 2: "high"}
    regime = atr_pct.fillna(0.5).apply(lambda p: regime_map.get(min(int(p * 3), 2), "mid")).astype(str)
    now = pd.Timestamp.now()
    test_years = sorted(set(y for y in range(now.year - years, now.year) if y >= 2016))
    all_trades = []
    for ty in test_years:
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train = X.index < cut
        test = (X.index >= cut) & (X.index <= eoy)
        if test.sum() < 20:
            continue
        X_tr = X[train]
        y_tr, y_te = compute_per_fold_labels(close, train, test, contract)
        X_te = X[test]
        if len(X_tr) < 200 or set(y_tr.unique()) != {0, 1, 2}:
            continue
        mc = y_tr.value_counts().min()
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(X_tr, y_tr, test_size=0.2, random_state=42,
                                                     stratify=y_tr if mc >= 2 else None)
        if set(y_tr2.unique()) != {0, 1, 2}:
            continue
        depth = MODEL_DEPTH.get(name, 2)
        model = xgb.XGBClassifier(n_estimators=300, max_depth=depth, learning_rate=0.02,
                                   objective="multi:softprob", num_class=3, random_state=42,
                                   n_jobs=1, tree_method="hist", verbosity=0)
        model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
        proba = model.predict_proba(X_te)
        sigs = _signals(proba, X_te.index)
        slm = SLTP_CFG.get(name, {}).get("sl", DEF_SL)
        tpm = SLTP_CFG.get(name, {}).get("tp", DEF_TP)
        tr = _simulate(sigs, close.reindex(X_te.index), high.reindex(X_te.index),
                       low.reindex(X_te.index), name, slm, tpm, atr, regime)
        if tr:
            logger.info("    %d: %d trades (TP=%d SL=%d flip=%d time=%d)", ty, len(tr),
                        sum(1 for t in tr if t["exit_reason"] == "tp"),
                        sum(1 for t in tr if t["exit_reason"] == "sl"),
                        sum(1 for t in tr if t["exit_reason"] == "signal_flip"),
                        sum(1 for t in tr if t["exit_reason"] == "time_stop"))
        all_trades.extend(tr)
    return all_trades


def flip_quality(trades: list[dict]) -> dict:
    """Analyze flip exits — compare exit price vs price 3 bars later."""
    df = pd.DataFrame(trades).sort_values(["asset", "entry_date"])
    flip_data = []
    for asset, g in df.groupby("asset"):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            t_cur = g.iloc[i]
            if t_cur["exit_reason"] != "signal_flip":
                continue
            has_next = i + 1 < len(g)
            if has_next:
                t_next = g.iloc[i + 1]
                drift_r = t_next["r_multiple"]
                drift_good = drift_r > 0
            else:
                drift_r = 0.0
                drift_good = False
            flip_data.append({
                "asset": asset, "entry_date": t_cur["entry_date"],
                "bars_held": t_cur["bars_held"], "r_multiple": t_cur["r_multiple"],
                "mae_r": t_cur["mae_r"], "mfe_r": t_cur["mfe_r"],
                "exit_price": t_cur["exit_price"], "side": t_cur["side"],
                "entry_price": t_cur["entry_price"],
                "next_r": drift_r, "next_positive": drift_good,
            })
    if not flip_data:
        return {}
    fd = pd.DataFrame(flip_data)
    n_pos_next = fd["next_positive"].sum()
    n_neg_next = (~fd["next_positive"]).sum()
    ff = {
        "total_flips_analyzed": len(fd),
        "next_positive": int(n_pos_next), "next_negative": int(n_neg_next),
        "next_positive_rate": float(n_pos_next / len(fd)),
        "avg_r": float(fd["r_multiple"].mean()),
        "avg_next_r": float(fd["next_r"].mean()),
        "avg_r_pos_next": float(fd[fd["next_positive"]]["r_multiple"].mean()),
        "avg_r_neg_next": float(fd[~fd["next_positive"]]["r_multiple"].mean()),
        "avg_mae_r": float(fd["mae_r"].mean()), "avg_mfe_r": float(fd["mfe_r"].mean()),
        "avg_bars": float(fd["bars_held"].mean()),
        "mae_mfe_ratio": float(fd["mfe_r"].mean() / max(fd["mae_r"].mean(), 0.001)),
    }
    ba = {}
    for asset, g in fd.groupby("asset"):
        if len(g) >= 3:
            ba[asset] = {"total": int(len(g)),
                         "next_positive_rate": float(g["next_positive"].mean()),
                         "avg_r": float(g["r_multiple"].mean()),
                         "avg_next_r": float(g["next_r"].mean()),
                         "mae_mfe": float(g["mfe_r"].mean() / max(g["mae_r"].mean(), 0.001))}
    ff["by_asset"] = ba
    return ff


def aggregate(trades: list[dict]) -> dict:
    if not trades:
        return {"n_trades": 0}
    df = pd.DataFrame(trades)
    o = {"n_trades": len(df), "n_assets": df["asset"].nunique(),
         "date_range": {"start": df["entry_date"].min(), "end": df["exit_date"].max()}}
    ret = df["return"]
    o["overall"] = {
        "win_rate": float((ret > 0).mean()), "loss_rate": float((ret < 0).mean()),
        "tp_rate": float((df["exit_reason"] == "tp").mean()),
        "sl_rate": float((df["exit_reason"] == "sl").mean()),
        "flip_rate": float((df["exit_reason"] == "signal_flip").mean()),
        "time_stop_rate": float((df["exit_reason"] == "time_stop").mean()),
        "avg_return": float(ret.mean()), "avg_r": float(df["r_multiple"].mean()),
        "median_r": float(df["r_multiple"].median()),
        "profit_factor": float(ret[ret > 0].sum() / abs(ret[ret < 0].sum() + 1e-9))}
    dur = {}
    for r in ["tp", "sl", "signal_flip", "time_stop"]:
        m = df["exit_reason"] == r
        if m.any():
            sd = df[m]
            dur[r] = {"count": int(m.sum()), "avg_bars": float(sd["bars_held"].mean()),
                       "median_bars": float(sd["bars_held"].median()),
                       "min_bars": int(sd["bars_held"].min()), "max_bars": int(sd["bars_held"].max()),
                       "std_bars": float(sd["bars_held"].std()), "avg_return": float(sd["return"].mean()),
                       "avg_r": float(sd["r_multiple"].mean())}
    o["duration_by_reason"] = dur
    bins, labels = [0, 3, 7, 14, 30, 60, 999], ["1-3d", "4-7d", "8-14d", "15-30d", "31-60d", "60d+"]
    df["bucket"] = pd.cut(df["bars_held"], bins=bins, labels=labels, right=True)
    dist = {}
    for bk, g in df.groupby("bucket", observed=True):
        dist[str(bk)] = {"count": len(g), "tp_rate": float((g["exit_reason"] == "tp").mean()),
                          "sl_rate": float((g["exit_reason"] == "sl").mean()),
                          "flip_rate": float((g["exit_reason"] == "signal_flip").mean()),
                          "win_rate": float((g["return"] > 0).mean()), "avg_r": float(g["r_multiple"].mean())}
    o["duration_distribution"] = dist
    ba = {}
    for a, g in df.groupby("asset"):
        ba[a] = {"n_trades": len(g), "win_rate": float((g["return"] > 0).mean()),
                  "avg_bars": float(g["bars_held"].mean()), "avg_r": float(g["r_multiple"].mean()),
                  "tp_rate": float((g["exit_reason"] == "tp").mean()),
                  "sl_rate": float((g["exit_reason"] == "sl").mean()),
                  "flip_rate": float((g["exit_reason"] == "signal_flip").mean()),
                  "avg_bars_tp": float(g[g["exit_reason"] == "tp"]["bars_held"].mean()) if (g["exit_reason"] == "tp").any() else 0,
                  "avg_bars_sl": float(g[g["exit_reason"] == "sl"]["bars_held"].mean()) if (g["exit_reason"] == "sl").any() else 0,
                  "avg_mae_r": float(g["mae_r"].mean()), "avg_mfe_r": float(g["mfe_r"].mean()),
                  "med_mae_r": float(g["mae_r"].median()), "med_mfe_r": float(g["mfe_r"].median())}
    o["by_asset"] = ba
    # Top performers by profit factor and avg R
    valid_ba = {k: v for k, v in ba.items() if v["n_trades"] >= 10}
    if valid_ba:
        pass
    # Overall MAE/MFE
    o["overall"]["avg_mae_r"] = float(df["mae_r"].mean())
    o["overall"]["avg_mfe_r"] = float(df["mfe_r"].mean())
    o["overall"]["med_mae_r"] = float(df["mae_r"].median())
    o["overall"]["med_mfe_r"] = float(df["mfe_r"].median())
    o["overall"]["efficiency"] = float(df["mfe_r"].mean() / max(df["mae_r"].mean(), 0.001))
    return o


def print_report(pt: dict, hist: dict, fq: dict | None = None):
    sep = "=" * 74
    print(f"\n{sep}")
    print("  QUANTFORGE TRADE ANALYSIS REPORT")
    print(sep)
    if pt and pt.get("n_trades", 0) > 0:
        print(f"\n  PHASE 1: PAPER TRADING ({pt['n_trades']} trades)")
        print(f"  Win/Loss:        {pt['win_rate']:.1%} / {pt['loss_rate']:.1%}")
        print(f"  TP / SL / Flip:  {pt['tp_rate']:.1%} / {pt['sl_rate']:.1%} / {pt['flip_rate']:.1%}")
        print(f"  Avg bars held:   {pt['avg_bars']:.1f}")
        print(f"  Avg return:      {pt['avg_return']:+.4f}")
        print(f"\n  By Asset:")
        print(f"  {'Asset':14s} {'Trades':>7s} {'Win%':>7s} {'AvgBars':>8s} {'TP%':>6s} {'SL%':>6s}")
        print(f"  {'-'*54}")
        for a, ba in sorted(pt.get("by_asset", {}).items()):
            print(f"  {a:14s} {ba['n']:>7d} {ba['win_rate']:>6.1%} {ba['avg_bars']:>7.1f} {ba['tp_rate']:>5.0%} {ba['sl_rate']:>5.0%}")
    if hist and hist.get("n_trades", 0) > 0:
        o = hist["overall"]
        print(f"\n  PHASE 2: HISTORICAL WALK-FORWARD BACKTEST")
        print(f"  {hist['n_trades']} trades, {hist['n_assets']} assets")
        print(f"  Period: {hist['date_range']['start']} to {hist['date_range']['end']}")
        print(f"  Win/Loss:        {o['win_rate']:.1%} / {o['loss_rate']:.1%}")
        print(f"  TP / SL / Flip:  {o['tp_rate']:.1%} / {o['sl_rate']:.1%} / {o['flip_rate']:.1%}")
        print(f"  Time stop rate:  {o['time_stop_rate']:.1%}")
        print(f"  Avg return:      {o['avg_return']:+.4f}")
        print(f"  Avg R:           {o['avg_r']:+.3f}")
        print(f"  Median R:        {o['median_r']:+.3f}")
        print(f"  Profit factor:   {o['profit_factor']:.3f}")
        dur = hist.get("duration_by_reason", {})
        print(f"\n  Trade Duration by Exit Reason:")
        print(f"  {'Reason':14s} {'Count':>6s} {'AvgBars':>8s} {'MedBars':>8s} {'Std':>7s} {'AvgR':>8s}")
        print(f"  {'-'*50}")
        for r in ["tp", "sl", "signal_flip", "time_stop"]:
            d = dur.get(r)
            if d and d["count"] > 0:
                print(f"  {r:14s} {d['count']:>6d} {d['avg_bars']:>7.1f} {d['median_bars']:>7.1f} {d['std_bars']:>6.1f} {d['avg_r']:>+7.3f}")
        dist = hist.get("duration_distribution", {})
        print(f"\n  Duration Distribution:")
        print(f"  {'Bucket':8s} {'Count':>6s} {'TP%':>6s} {'SL%':>6s} {'Flip%':>7s} {'Win%':>6s} {'AvgR':>7s}")
        print(f"  {'-'*55}")
        for b in ["1-3d", "4-7d", "8-14d", "15-30d", "31-60d", "60d+"]:
            d = dist.get(b)
            if d:
                print(f"  {b:8s} {d['count']:>6d} {d['tp_rate']:>5.0%} {d['sl_rate']:>5.0%} {d['flip_rate']:>6.0%} {d['win_rate']:>5.0%} {d['avg_r']:>+6.3f}")
        oo = hist.get("overall", {})
        if "avg_mae_r" in oo:
            print(f"\n  MAE / MFE (avg R):  {oo['avg_mae_r']:+.2f}R / {oo['avg_mfe_r']:+.2f}R  "
                  f"(med: {oo['med_mae_r']:+.2f}R / {oo['med_mfe_r']:+.2f}R)")
            print(f"  Efficiency (MFE/MAE):  {oo['efficiency']:.2f}")
        if fq:
            print(f"\n  Flip Quality Analysis:")
            print(f"  Total flips: {fq['total_flips_analyzed']}")
            print(f"  Next trade positive: {fq['next_positive']} ({fq['next_positive_rate']:.1%})   "
                  f"Negative: {fq['next_negative']} ({1 - fq['next_positive_rate']:.1%})")
            print(f"  Avg R on flip exit: {fq['avg_r']:+.3f}   Avg next R: {fq['avg_next_r']:+.3f}")
            print(f"  Avg R (next pos): {fq['avg_r_pos_next']:+.3f}   "
                  f"(next neg): {fq['avg_r_neg_next']:+.3f}")
            print(f"  Avg MAE R: {fq['avg_mae_r']:+.2f}   Avg MFE R: {fq['avg_mfe_r']:+.2f}   "
                  f"MFE/MAE: {fq['mae_mfe_ratio']:.2f}")
            fba = fq.get("by_asset", {})
            if fba:
                ranked = sorted(fba.items(), key=lambda kv: kv[1]["next_positive_rate"])
                print(f"\n  Worst flip quality (>=3 flips):")
                print(f"  {'Asset':12s} {'Total':>6s} {'PosNext%':>9s} {'AvgR':>7s} {'AvgNextR':>9s} {'MaeMfe':>7s}")
                print(f"  {'-'*55}")
                for a, b in ranked[:8]:
                    print(f"  {a:12s} {b['total']:>6d} {b['next_positive_rate']:>8.0%} {b['avg_r']:>+6.3f} {b['avg_next_r']:>+8.3f} {b['mae_mfe']:>6.2f}")
        ba = hist.get("by_asset", {})
        print(f"\n  By Asset:")
        print(f"  {'Asset':12s} {'Trades':>7s} {'Win%':>7s} {'AvgBars':>8s} {'AvgR':>7s} {'TP%':>6s} {'SL%':>6s} {'BarsTP':>7s} {'BarsSL':>7s} {'MAE_R':>7s} {'MFE_R':>7s}")
        print(f"  {'-'*95}")
        for a in sorted(ba.keys()):
            b = ba[a]
            print(f"  {a:12s} {b['n_trades']:>7d} {b['win_rate']:>6.1%} {b['avg_bars']:>7.1f} {b['avg_r']:>+6.3f} {b['tp_rate']:>5.0%} {b['sl_rate']:>5.0%} {b['avg_bars_tp']:>6.1f} {b['avg_bars_sl']:>6.1f} {b['avg_mae_r']:>+6.2f} {b['avg_mfe_r']:>+6.2f}")
        # Top performers by efficiency (MFE/MAE ratio)
        valid = {k: v for k, v in ba.items() if v["n_trades"] >= 10}
        if valid:
            ranked = sorted(valid.items(), key=lambda kv: kv[1]["avg_mfe_r"] / max(kv[1]["avg_mae_r"], 0.001), reverse=True)
            print(f"\n  ---")
            print(f"  Top performers by MFE/MAE efficiency (>=10 trades):")
            print(f"  {'Asset':12s} {'Trades':>7s} {'Win%':>7s} {'AvgR':>8s} {'MFE/MAE':>8s} {'MAE_R':>7s} {'MFE_R':>7s}")
            print(f"  {'-'*64}")
            for a, b in ranked[:10]:
                eff = b["avg_mfe_r"] / max(b["avg_mae_r"], 0.001)
                print(f"  {a:12s} {b['n_trades']:>7d} {b['win_rate']:>6.1%} {b['avg_r']:>+7.3f} {eff:>7.2f} {b['avg_mae_r']:>+6.2f} {b['avg_mfe_r']:>+6.2f}")
    print()


def main(targets: Optional[list] = None, years: int = 3):
    if targets is None:
        targets = list(DASHBOARD_TICKERS.keys())
    print("\n  Phase 1: Paper trade analysis…")
    pts = analyze_paper_trades()
    ps = paper_stats(pts)
    if ps:
        print(f"    {ps['n_trades']} trades, win rate {ps['win_rate']:.1%}")
    else:
        print("    No paper trades found.")
    print("\n  Phase 2: Historical backtest…")
    print("    Loading macro data…")
    macro = load_macro()
    need_ref = any(FEATURE_REGISTRY[t].requires_ref for t in (targets or FEATURE_REGISTRY) if t in FEATURE_REGISTRY)
    ref = fetch_ohlcv("SPY", years + 10) if need_ref else None
    assets = targets or list(FEATURE_REGISTRY.keys())
    all_trades, failed = [], []
    for t in assets:
        if t not in FEATURE_REGISTRY:
            failed.append(t)
            continue
        try:
            r = ref if FEATURE_REGISTRY[t].requires_ref else None
            tr = backtest_asset(t, macro, r, years)
            all_trades.extend(tr)
        except Exception as e:
            logger.error("  %s: %s", t, e)
            failed.append(t)
    print(f"\n    {len(all_trades)} trades across {len(assets) - len(failed)} assets")
    if failed:
        print(f"    {len(failed)} assets failed: {', '.join(failed[:5])}")
    print("\n  Phase 3: Report…")
    hs = aggregate(all_trades)
    fq = flip_quality(all_trades)
    print_report(ps, hs, fq)
    out = os.path.join(BASE, "data", "live", "trade_analysis.json")
    with open(out, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "paper": ps, "historical": hs, "failed": failed}, f, indent=2)
    print(f"  Results saved to {out}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--assets", nargs="+", help="Specific tickers (default: dashboard assets)")
    p.add_argument("--years", type=int, default=3, help="Walk-forward years (default: 3)")
    p.add_argument("--quick", action="store_true", help="Paper trade analysis only")
    a = p.parse_args()
    if a.quick:
        print_report(paper_stats(analyze_paper_trades()), {})
    else:
        main(a.assets, a.years)
