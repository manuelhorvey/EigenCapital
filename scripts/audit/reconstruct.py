"""Phase 2 — Trade lifecycle reconstruction harness (read-only, offline).

PREREGISTERED CONVENTIONS (fixed before results were observed):
 C1. Signal math parity-verified against scripts/r4_rebalance_loop.compute_r4_signal
     (frozen implementation IMPORTED, not copied; probe asserts equality).
 C2. Signal universe = all [broker.allowed_symbols] keys (mirrors live loop,
     including symbols ineligible for trading). Trading universe = eligible keys.
 C3. Missing local D1 crosses synthesized from USD legs (ratio of OHLC),
     inner-joined on shared dates. Derived-data flag recorded.
 C4. Decisions each trading day (primary, mirrors r4_daily.sh); every 5th trading
     day = weekly-declared sensitivity.
 C5. Regime OFF: NO exits, NO resizing — positions ride unmanaged (exact live-loop
     behavior; run_cycle() returns before order generation when regime is off).
 C6. Episodes: open when a symbol enters top-8 eligible with |w|>0.005; close on
     top-8 exit, sign flip, or end of data. Episode weight frozen at entry value
     for episode statistics (resizing captured in portfolio curve).
 C7. Costs: 10 bps per side (campaign convention turnover*0.001); sensitivity
     +5 bps slippage per side. Swap/commission zero per live broker evidence.
 C8. Execution price: decision-day close (signal uses bars <= t; live executes
     immediately after computing on completed bars).
 C9. MFE/MAE in price-return space vs entry, from D1 high/low path.
 C10. No look-ahead: quantities at row t use data <= t.

Outputs:
  reports/r4_economics_audit/trades.csv / .parquet / trades_weekly.csv
  reports/r4_economics_audit/trades.schema.json
  reports/r4_economics_audit/reconstruction_config.json
  reports/r4_economics_audit/portfolio_curve_daily.csv
  reports/r4_economics_audit/trades_pathdata.parquet
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports" / "r4_economics_audit"
DATA = REPO / "data" / "mt5"

sys.path.insert(0, str(REPO / "src"))
from eigencapital.config import load_config  # noqa: E402

COST_PER_SIDE_BPS = 10.0
SLIPPAGE_SENS_BPS = 5.0

NATIVE = {
    "AUDUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "NZDUSD",
    "XAUUSD", "XAGUSD", "US500", "US30", "USTEC", "BTCUSD", "ETHUSD", "USOIL",
}

LOOKBACK, SKIP, RISK_LB, VOL_LB = 252, 21, 20, 60


def _load_loop_module():
    spec = importlib.util.spec_from_file_location(
        "r4_rebalance_loop", REPO / "scripts" / "r4_rebalance_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_native_frame(symbol: str) -> pd.DataFrame | None:
    path = DATA / f"{symbol}m_D1.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["time"])
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close"]]


def ratio_frames(num: pd.DataFrame, den: pd.DataFrame) -> pd.DataFrame:
    idx = num.index.intersection(den.index)
    n, d = num.loc[idx], den.loc[idx]
    hi = np.maximum(n["high"] / d["low"], n["low"] / d["high"])
    lo = np.minimum(n["high"] / d["low"], n["low"] / d["high"])
    return pd.DataFrame(
        {"open": n["open"] / d["open"], "high": hi, "low": lo, "close": n["close"] / d["close"]},
        index=idx,
    )


def invert_frames(f: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": 1.0 / f["open"], "high": 1.0 / f["low"],
         "low": 1.0 / f["high"], "close": 1.0 / f["close"]},
        index=f.index,
    )


def build_universe(allowed: dict[str, str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    derived: list[str] = []
    for sym in allowed:
        if sym in NATIVE:
            f = load_native_frame(sym)
            if f is not None:
                frames[sym] = f

    # Pre-pass: register inverted USD-base synthetics (AUD_xUSD from AUDUSD,
    # CHF_xUSD from USDCHF, ...) so arbitrary crosses have two legs.
    for sym in list(frames.keys()):
        if sym.endswith("USD") and sym[:-3] != "USD":
            inv_name = sym[:-3] + "_xUSD"
            if inv_name not in frames:
                frames[inv_name] = invert_frames(frames[sym])
                derived.append(inv_name)
        elif sym.startswith("USD") and len(sym) > 3:
            inv_name = sym[3:] + "_xUSD"
            if inv_name not in frames:
                frames[inv_name] = invert_frames(frames[sym])
                derived.append(inv_name)

    pending = [s for s in allowed if s not in frames]
    for _ in range(4):
        still = []
        for sym in pending:
            base, quote = sym[:3], sym[3:]
            f = None
            if quote == "USD":
                src = frames.get(base + "USD")
                if src is not None:
                    f = src.copy()
            elif base == "USD":
                src = frames.get(quote + "USD")
                if src is not None:
                    f = invert_frames(src)
            else:
                nb = frames.get(base + "USD", frames.get(base + "_xUSD"))
                dq = frames.get(quote + "USD", frames.get(quote + "_xUSD"))
                if nb is not None and dq is not None:
                    f = ratio_frames(nb, dq)
            if f is not None:
                frames[sym] = f
                derived.append(sym)
            else:
                still.append(sym)
        pending = still
        if not pending:
            break
    return frames, sorted(set(derived))


def replicate_signal(close_wide: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    returns_df = close_wide.pct_change()
    returns_df = returns_df.dropna(how="all").ffill().fillna(0)

    mom_12m = (1 + returns_df).rolling(LOOKBACK).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(SKIP).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom_12m - mom_1m).dropna(how="all")

    rk = sig.rank(axis=1, pct=True)
    w = rk - 0.5

    avg_vol = returns_df.rolling(RISK_LB).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)

    vol60 = returns_df.rolling(VOL_LB).std() * np.sqrt(252)
    vol_scale = np.minimum(vol60 / 0.50, 1.0)

    fin = w.multiply(regime, axis=0) * vol_scale
    fin = fin.clip(-0.20, 0.20)
    if "BTCUSD" in fin.columns:
        fin["BTCUSD"] = fin["BTCUSD"].clip(-0.10, 0.10)

    regime_on = avg_vol < risk_median
    return fin, regime_on


def _update_open_paths(holdings, t, close_wide, high_wide, low_wide, regime_off_day: bool) -> None:
    for s, h in holdings.items():
        try:
            c = float(close_wide[s].loc[t])
            hi = float(high_wide[s].loc[t])
            lo = float(low_wide[s].loc[t])
        except (KeyError, TypeError, ValueError):
            continue
        if np.isnan(c) or np.isnan(hi) or np.isnan(lo):
            continue
        d = h["dir"]
        ret_today = d * (c / h["entry_price"] - 1.0)
        fav = d * (hi / h["entry_price"] - 1.0)
        adv = d * (lo / h["entry_price"] - 1.0)
        h["days"] += 1
        h["cum_ret"] = ret_today
        h["path"].append((str(pd.Timestamp(t).date()), c, ret_today))
        if regime_off_day:
            h["n_regime_off_days"] += 1
        if adv < h["mae"]:
            h["mae"] = adv
            h["t_mae"] = h["days"]
        if fav > h["mfe"]:
            h["mfe"] = fav
            h["t_mfe"] = h["days"]
        peak = max(x[2] for x in h["path"])
        h["max_intrade_dd"] = min(h["max_intrade_dd"], ret_today - peak)


def _close_episode(holdings, s, t, exit_px, reason, label) -> dict:
    h = holdings.pop(s)
    d = h["dir"]
    gross = d * (float(exit_px) / h["entry_price"] - 1.0)
    net = gross - (COST_PER_SIDE_BPS * 2) / 1e4
    net_slip = gross - ((COST_PER_SIDE_BPS + SLIPPAGE_SENS_BPS) * 2) / 1e4
    hold_cal = (pd.Timestamp(t) - pd.Timestamp(h["entry_dt"])).days
    return {
        "symbol": s,
        "direction": "LONG" if d > 0 else "SHORT",
        "entry_ts": h["entry_dt"],
        "exit_ts": t,
        "entry_price": round(h["entry_price"], 6),
        "exit_price": round(float(exit_px), 6),
        "holding_calendar_days": int(hold_cal),
        "holding_trading_days": int(h["days"]),
        "signal_strength_entry": round(h["sig_strength_entry"], 5),
        "rank_at_entry": int(h["rank_at_entry"]),
        "gross_return": round(gross, 6),
        "net_return_10bps_side": round(net, 6),
        "net_return_15bps_side": round(net_slip, 6),
        "cost_roundtrip_bps": COST_PER_SIDE_BPS * 2,
        "mfe": round(h["mfe"], 6),
        "mae": round(h["mae"], 6),
        "time_to_mfe_trading_days": int(h["t_mfe"]),
        "time_to_mae_trading_days": int(h["t_mae"]),
        "max_intradrawdown_from_peak": round(h["max_intrade_dd"], 6),
        "exit_reason": reason,
        "profitable_net": bool(net > 0),
        "regime_off_days_during_trade": int(h["n_regime_off_days"]),
        "cadence_label": label,
        "_path": h["path"],
    }


def build_episodes(
    fin, regime_on, high_wide, low_wide, close_wide,
    eligible, decision_mask=None, label="daily",
) -> pd.DataFrame:
    dates = fin.index
    mask = decision_mask if decision_mask is not None else pd.Series(True, index=dates)

    holdings: dict[str, dict] = {}
    closed: list[dict] = []

    for t in dates:
        w_row = fin.loc[t]
        if w_row.isna().all():
            continue

        decided = bool(mask.loc[t])
        regime_on_t = bool(regime_on.loc[t]) if t in regime_on.index else False

        if not decided or not regime_on_t:
            off_day = decided and not regime_on_t
            _update_open_paths(holdings, t, close_wide, high_wide, low_wide, off_day)
            continue

        active = [
            (s, float(w_row[s])) for s in eligible
            if s in w_row.index and np.isfinite(w_row[s]) and abs(float(w_row[s])) > 0.005
        ]
        active.sort(key=lambda x: abs(x[1]), reverse=True)
        target = dict(active[:8])
        target_syms = set(target)
        strength_order = [abs(w) for _, w in active]

        for s in list(holdings):
            h = holdings[s]
            if s not in target_syms:
                px = close_wide[s].get(t, np.nan)
                if np.isfinite(px):
                    closed.append(_close_episode(holdings, s, t, float(px), "rotated_out_top8", label))
            elif np.sign(target[s]) != np.sign(h["w_entry"]):
                px = close_wide[s].get(t, np.nan)
                if np.isfinite(px):
                    closed.append(_close_episode(holdings, s, t, float(px), "sign_flip", label))

        for s in target_syms:
            if s in holdings:
                continue
            px = close_wide[s].get(t, np.nan) if s in close_wide.columns else np.nan
            if not np.isfinite(px):
                continue
            holdings[s] = {
                "symbol": s,
                "dir": 1 if target[s] > 0 else -1,
                "entry_dt": t,
                "entry_price": float(px),
                "w_entry": float(target[s]),
                "rank_at_entry": strength_order.index(abs(target[s])) + 1,
                "sig_strength_entry": float(target[s]),
                "n_regime_off_days": 0,
                "mae": 0.0,
                "mfe": 0.0,
                "t_mae": 0,
                "t_mfe": 0,
                "days": 0,
                "max_intrade_dd": 0.0,
                "cum_ret": 0.0,
                "label": label,
                "path": [],
            }

        _update_open_paths(holdings, t, close_wide, high_wide, low_wide, False)

    last_t = dates[-1]
    for s in list(holdings):
        ser = close_wide[s].dropna()
        px = float(ser.iloc[-1]) if len(ser) else np.nan
        if np.isfinite(px):
            closed.append(_close_episode(holdings, s, last_t, px, "end_of_data", label))

    return pd.DataFrame(closed)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config("production")
    allowed = dict(config.broker.allowed_symbols)
    eligible = [s for s, cls in allowed.items() if not cls.endswith("_excluded")]

    mod = _load_loop_module()

    frames, derived = build_universe(allowed)
    missing = [s for s in allowed if s not in frames]
    signal_syms = [s for s in sorted(frames.keys()) if s in allowed]

    close_wide = pd.DataFrame(
        {s: frames[s]["close"] for s in signal_syms}
    ).sort_index()
    high_wide = pd.DataFrame({s: frames[s]["high"] for s in signal_syms}).reindex(close_wide.index)
    low_wide = pd.DataFrame({s: frames[s]["low"] for s in signal_syms}).reindex(close_wide.index)

    fin, regime_on = replicate_signal(close_wide)

    # ── Parity probes vs frozen implementation (FULL universe: ranks
    #    are cross-sectional, so subsets would legitimately differ) ──
    rng = np.random.default_rng(7)
    probe_syms = signal_syms
    parity_ok = True
    parity_detail = []
    for _ in range(3):
        cut = int(rng.integers(len(close_wide) // 2, len(close_wide)))
        sub = {s: close_wide[[s]].iloc[:cut].rename(columns={s: "close"}).copy()
               for s in probe_syms}
        latest_mod, diag_mod = mod.compute_r4_signal(sub)
        # align on the frozen function's own last-valid-return row
        r_sub_idx = (
            pd.DataFrame({s: sub[s]["close"].pct_change() for s in probe_syms})
            .dropna(how="all").index
        )
        target_ts = r_sub_idx[-1]
        latest_rep = fin.loc[target_ts]
        common = [c for c in latest_mod.index if c in probe_syms]
        eq = np.allclose(
            latest_mod[common].astype(float).to_numpy(),
            latest_rep[common].astype(float).to_numpy(),
            atol=1e-9, equal_nan=True,
        )
        # regime parity: recompute avg_vol over identical input
        rets_sub = close_wide[probe_syms].iloc[:cut].pct_change().dropna(how="all").ffill().fillna(0)
        av = rets_sub.rolling(RISK_LB).std().mean(axis=1) * np.sqrt(252)
        rm = av.expanding().median()
        reg_eq = bool(av.iloc[-1] < rm.iloc[-1]) == bool(diag_mod["regime_on"])
        parity_detail.append({"cut_row": cut, "weights_equal": bool(eq), "regime_equal": bool(reg_eq)})
        if not (eq and reg_eq):
            parity_ok = False
    print(f"parity_vs_frozen_compute_r4_signal: {parity_ok}")
    print(json.dumps(parity_detail))

    trades = build_episodes(fin, regime_on, high_wide, low_wide, close_wide, eligible, label="daily")

    wk_mask = pd.Series(False, index=fin.index)
    wk_mask.iloc[::5] = True
    trades_weekly = build_episodes(fin, regime_on, high_wide, low_wide, close_wide, eligible,
                                   decision_mask=wk_mask, label="weekly")

    # ── Portfolio curve (exact w-path) ─────────────────────────────
    rets = close_wide.reindex(fin.index).pct_change()
    expo = fin.shift(1).fillna(0.0)
    port_gross = (expo * rets).sum(axis=1)
    turnover = fin.diff().abs().sum(axis=1).fillna(0.0)
    port_net = port_gross - turnover * COST_PER_SIDE_BPS / 1e4
    curve = pd.DataFrame({
        "gross_exposure": expo.abs().sum(axis=1),
        "net_exposure": expo.sum(axis=1),
        "n_positions": (expo.abs() > 0.005).sum(axis=1),
        "ret_gross_weighted": port_gross,
        "ret_net_weighted": port_net,
        "turnover_weight_units": turnover,
        "regime_on": regime_on.reindex(fin.index).astype(float),
    })
    curve.to_csv(OUT / "portfolio_curve_daily.csv")

    trades_out = trades.drop(columns=["_path"]) if "_path" in trades else trades
    trades_out.to_csv(OUT / "trades.csv", index=False)
    trades_out.to_parquet(OUT / "trades.parquet", index=False)
    tw = trades_weekly.drop(columns=["_path"]) if "_path" in trades_weekly else trades_weekly
    tw.to_csv(OUT / "trades_weekly.csv", index=False)

    path_rows = []
    if "_path" in trades:
        for i, tr in trades.iterrows():
            for dt, px, cr in tr["_path"]:
                path_rows.append({"trade_id": int(i), "symbol": tr["symbol"], "date": dt,
                                  "price": px, "cum_return": round(cr, 6)})
    pd.DataFrame(path_rows).to_parquet(OUT / "trades_pathdata.parquet", index=False)

    schema = {
        "description": "R4 reconstructed trade dataset (simulation-based; NOT broker fills)",
        "preregistered_conventions": {
            "C1_parity_verified": parity_ok,
            "C2_signal_universe": sorted(allowed.keys()),
            "C2_tradeable_subset": sorted(eligible),
            "C3_synthesized_symbols": derived,
            "C4_cadence_primary": "daily",
            "C4_cadence_sensitivity": "every_5th_trading_day",
            "C5_regime_off_behavior": "positions ride unmanaged (live-faithful)",
            "C6_episode_rule": "top-8 eligible |w|>0.005; exits rotated_out_top8/sign_flip/end_of_data; weight frozen at entry for stats",
            "C7_costs": {"per_side_bps": COST_PER_SIDE_BPS,
                         "slippage_sensitivity_bps_per_side": SLIPPAGE_SENS_BPS},
            "C8_execution_price": "decision-day close",
            "C9_mae_mfe_space": "price-return vs entry, D1 high/low path",
            "C10_lookahead": "none",
        },
        "data_window": {"start": str(close_wide.index.min().date()),
                        "end": str(close_wide.index.max().date())},
        "universe_available": sorted(frames.keys()),
        "universe_missing_locally": sorted(missing),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "trades.schema.json").write_text(json.dumps(schema, indent=2))

    cfg = {
        "git_head": "d16148e",
        "frozen_identity": "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb",
        "eligible_symbols": sorted(eligible),
        "n_trades_daily": int(len(trades)),
        "n_trades_weekly": int(len(trades_weekly)),
        "signal_first_valid": str(fin.dropna(how="all").index.min()),
        "parity_check_passed": bool(parity_ok),
        "parity_probes": parity_detail,
    }
    (OUT / "reconstruction_config.json").write_text(json.dumps(cfg, indent=2))

    print(f"trades(daily)={len(trades)} trades(weekly)={len(trades_weekly)}")
    print(f"data_window={schema['data_window']}")
    print(f"missing_locally={sorted(missing)}")


if __name__ == "__main__":
    main()
