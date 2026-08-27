"""Phases 3-7 — Core economics analyses over the reconstructed trade dataset.

Preregistered metric definitions:
 R (risk unit) := ATR14(%) at entry date = mean of last 14 true ranges / entry price.
 Touch tests use D1 high/low. Stop-priority within bar: pessimistic (stop before TP).
 Forward-return horizons measured on the traded symbol's close series in trade direction,
 independent of actual exit (pure entry-quality question).
 Recovery curves: conditional on path minimum reaching X (in R), report final outcome.
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


def atr14_pct_per_symbol(frames: dict, symbols: list) -> pd.DataFrame:
    """ATR14% computed per symbol on ITS OWN calendar (union-calendar shifts
    would poison TR with foreign-row NaNs)."""
    out = {}
    for s in symbols:
        f = frames[s]
        pc = f["close"].shift(1)
        tr = pd.concat(
            [f["high"] - f["low"], (f["high"] - pc).abs(), (f["low"] - pc).abs()],
            axis=1,
        ).max(axis=1)
        out[s] = tr.rolling(14, min_periods=10).mean() / f["close"]
    return pd.DataFrame(out)


def jdump(obj, name: str) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, default=str))
    print(f"wrote {name}")


def fwd_returns(trades: pd.DataFrame, close_wide: pd.DataFrame, bars_list) -> dict:
    out = {}
    dirsign = trades["direction"].map({"LONG": 1, "SHORT": -1}).to_numpy()
    entry_loc = close_wide.index.get_indexer(pd.DatetimeIndex(trades["entry_ts"]))
    sym_loc = close_wide.columns.get_indexer(trades["symbol"].to_numpy())
    mat = close_wide.to_numpy()
    n_rows = len(close_wide)
    for b in bars_list:
        idx_exit = np.clip(entry_loc + b, 0, n_rows - 1)
        px_entry = mat[entry_loc, sym_loc]
        px_fwd = mat[idx_exit, sym_loc]
        valid = (entry_loc >= 0) & (sym_loc >= 0) & (entry_loc + b < n_rows)
        fr = np.where(valid, dirsign * (px_fwd / px_entry - 1.0), np.nan)
        fr = pd.Series(fr, index=trades.index).dropna()
        out[f"fwd_{b}bar"] = {
            "n": int(len(fr)),
            "mean": float(fr.mean()),
            "median": float(fr.median()),
            "win_rate": float((fr > 0).mean()),
        }
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config("production")
    allowed = dict(config.broker.allowed_symbols)
    frames, derived = rec.build_universe(allowed)
    signal_syms = [s for s in sorted(frames) if s in allowed]
    close_wide = pd.DataFrame({s: frames[s]["close"] for s in signal_syms}).sort_index()

    trades = pd.read_parquet(OUT / "trades.parquet")
    trades["entry_ts"] = pd.to_datetime(trades["entry_ts"])
    trades["exit_ts"] = pd.to_datetime(trades["exit_ts"])
    net = "net_return_10bps_side"

    # ── sanity: top winners ────────────────────────────────────────
    top = trades.nlargest(8, net)[
        [
            "symbol",
            "direction",
            "entry_ts",
            "exit_ts",
            "holding_trading_days",
            "gross_return",
            net,
        ]
    ]
    print("\n[top winners sanity]")
    print(top.to_string(index=False))

    # ATR14% per symbol/day → R at entry
    atr = atr14_pct_per_symbol(frames, signal_syms).reindex(close_wide.index)
    e_idx = close_wide.index.get_indexer(pd.DatetimeIndex(trades["entry_ts"]))
    sym_arr = trades["symbol"].to_numpy()
    r_atr = np.array(
        [
            float(atr[s].iloc[e]) if e >= 0 and np.isfinite(atr[s].iloc[e]) else np.nan
            for s, e in zip(sym_arr, e_idx)
        ]
    )
    trades["atr14pct_at_entry"] = r_atr
    trades["R_price_space"] = r_atr

    # ── Phase 3: entry quality ─────────────────────────────────────
    eq: dict = {"horizons_bars": [1, 3, 5, 10, 20, 60]}
    eq.update(fwd_returns(trades, close_wide, eq["horizons_bars"]))

    # MFE/MAE efficiency + adverse-first + early failure (R space)
    mfe_r = trades["mfe"] / trades["R_price_space"]
    mae_r = -trades["mae"] / trades["R_price_space"]
    trades["mfe_R"], trades["mae_R"] = mfe_r, mae_r
    adverse_first = ((mae_r > 0.25) & (mfe_r < 0.25)).mean()
    early_fail = ((mae_r > 0.5) & (trades["time_to_mae_trading_days"] <= 5)).mean()
    eq["mfe_mae"] = {
        "mfe_R_median": float(mfe_r.median()),
        "mae_R_median": float(mae_r.median()),
        "mfe_over_mae_ratio_median": float((mfe_r / mae_r.replace(0, np.nan)).median()),
        "adverse_first_ratio_p25R_before_mfe25R": float(adverse_first),
        "early_failure_rate_05R_within_5bars": float(early_fail),
        "immediate_adverse_move_share_any_negative_mae": float((mae_r > 0).mean()),
        "prob_reach_plus_1R": float((mfe_r >= 1).mean()),
        "prob_reach_minus_1R": float((mae_r >= 1).mean()),
        "prob_reach_plus_2R": float((mfe_r >= 2).mean()),
        "prob_reach_minus_2R": float((mae_r >= 2).mean()),
    }
    # time-to-profit / time-to-loss from pathdata
    paths = pd.read_parquet(OUT / "trades_pathdata.parquet")
    ttp, ttl = [], []
    for tid, g in paths.groupby("trade_id"):
        pos = g[g["cum_return"] > 0]
        neg = g[g["cum_return"] < 0]
        ttp.append(
            int(g.loc[pos.index[0], "date"])
            if False
            else (g.index.get_loc(pos.index[0]) if len(pos) else None)
        )
        ttl.append(g.index.get_loc(neg.index[0]) if len(neg) else None)
    trades["time_to_profit_bars"] = [x + 1 if x is not None else np.nan for x in ttp]
    trades["time_to_loss_bars"] = [x + 1 if x is not None else np.nan for x in ttl]
    eq["time_to_profit_bars_median"] = float(trades["time_to_profit_bars"].median())
    eq["time_to_loss_bars_median"] = float(trades["time_to_loss_bars"].median())
    eq["nan_R_share"] = float(trades["R_price_space"].isna().mean())
    jdump(eq, "entry_quality.json")
    trades.to_parquet(OUT / "trades_enriched.parquet")

    # ── Phase 4: signal strength quintiles/deciles ────────────────
    def bucket_stats(df: pd.DataFrame, col: str, q: int) -> list[dict]:
        rows: list[dict] = []
        try:
            buckets = pd.qcut(df[col].abs(), q, labels=False, duplicates="drop")
        except ValueError:
            return rows
        for b, g in df.groupby(buckets):
            r = g[net]
            rows.append(
                {
                    "bucket": int(b),
                    "n": int(len(g)),
                    "signal_strength_mean": float(g[col].abs().mean()),
                    "expectancy_net": float(r.mean()),
                    "win_rate": float((r > 0).mean()),
                    "sharpe_per_trade": float(r.mean() / r.std())
                    if r.std() > 0
                    else None,
                    "mfe_R_median": float(g["mfe_R"].median()),
                    "mae_R_median": float(g["mae_R"].median()),
                    "hold_days_median": float(g["holding_trading_days"].median()),
                    "tail_loss_P05": float(r.quantile(0.05)),
                    "prob_plus_1R": float((g["mfe_R"] >= 1).mean()),
                    "prob_minus_1R": float((g["mae_R"] >= 1).mean()),
                }
            )
        return rows

    ss: dict = {
        "quintiles_by_abs_signal": bucket_stats(trades, "signal_strength_entry", 5),
        "deciles_by_abs_signal": bucket_stats(trades, "signal_strength_entry", 10),
        "quintiles_by_rank_at_entry": bucket_stats(
            trades.assign(rank_at_entry=-trades["rank_at_entry"]), "rank_at_entry", 5
        ),
    }
    q = ss["quintiles_by_abs_signal"]
    exps = [b["expectancy_net"] for b in q]
    from scipy.stats import spearmanr

    rho, p = spearmanr(range(len(exps)), exps)
    ss["monotonicity_expectancy_spearman"] = {"rho": float(rho), "p_value": float(p)}
    ss["monotonicity_holds"] = bool(
        exps == sorted(exps) or exps == sorted(exps, reverse=True)
    )
    jdump(ss, "signal_strength.json")

    # ── Phase 5: holding-period economics ──────────────────────────
    bins = [0, 2, 5, 10, 20, 40, 10**6]
    labels = ["1-2d", "3-5d", "6-10d", "11-20d", "21-40d", "40d+"]
    hb = []
    total_pos = trades.loc[trades[net] > 0, net].sum()
    for lab_i in range(len(labels)):
        lo, hi = bins[lab_i], bins[lab_i + 1]
        g = trades[
            (trades["holding_trading_days"] >= lo)
            & (trades["holding_trading_days"] < hi)
        ]
        if len(g) == 0:
            continue
        r = g[net]
        wins, losses = r[r > 0], r[r < 0]
        hb.append(
            {
                "bucket": labels[lab_i],
                "n": int(len(g)),
                "share_of_trades": round(len(g) / len(trades), 4),
                "expectancy_net": float(r.mean()),
                "win_rate": float((r > 0).mean()),
                "avg_win": float(wins.mean()) if len(wins) else 0.0,
                "avg_loss": float(losses.mean()) if len(losses) else 0.0,
                "sum_net_contribution": float(r.sum()),
                "contribution_share_of_positive_pnl": float(r[r > 0].sum() / total_pos)
                if total_pos
                else None,
                "mae_R_median": float(g["mae_R"].median()),
                "mfe_R_median": float(g["mfe_R"].median()),
                "sharpe_per_trade": float(r.mean() / r.std()) if r.std() > 0 else None,
                "financing": 0.0,
                "prob_recovery_given_loser": float((g.loc[r < 0, "mfe_R"] > 1).mean())
                if (r < 0).any()
                else None,
            }
        )
    hp = {
        "buckets_trading_days": hb,
        "percentiles_trading_days": {
            k: float(v)
            for k, v in trades["holding_trading_days"]
            .quantile([0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
            .items()
        },
    }
    jdump(hp, "holding_period.json")

    # ── Phase 6: loss dynamics ─────────────────────────────────────
    thresholds_R = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    min_r = trades["mae_R"]  # positive magnitude: deepest adverse excursion in R
    recovery = []
    for th in thresholds_R:
        hit = trades[min_r >= th]
        if len(hit) == 0:
            continue
        worse = hit[hit["mae_R"] >= th + 0.25]
        recovery.append(
            {
                "threshold_R": th,
                "n_reached": int(len(hit)),
                "pct_eventually_profitable_net": float((hit[net] > 0).mean()),
                "avg_final_return_R": float((hit[net] / hit["R_price_space"]).mean()),
                "pct_deteriorated_further_025R": float(len(worse) / max(len(hit), 1)),
                "median_additional_mae_beyond_threshold_R": float(
                    (worse["mae_R"] - th).median()
                )
                if len(worse)
                else 0.0,
            }
        )
    losers = trades[trades[net] <= 0]
    ld = {
        "loss_speed": {
            "time_to_mae_bars_median_losers": float(
                losers["time_to_mae_trading_days"].median()
            ),
            "within_5_bars_share": float(
                (losers["time_to_mae_trading_days"] <= 5).mean()
            ),
        },
        "underwater": {
            "note": "cumulative path negative share computed from pathdata",
        },
        "ever_profitable_among_losers": float((losers["mfe_R"] > 0.25).mean())
        if len(losers)
        else None,
        "recovery_curves": recovery,
    }
    # underwater duration from paths
    uw = []
    for _tid, g in paths.groupby("trade_id"):
        uw.append(float((g["cum_return"] < 0).mean()))
    uw_dict: dict = {
        "note": "cumulative path negative share from pathdata",
        "median_time_underwater_share": float(np.median(uw)),
    }
    ld["underwater"] = uw_dict
    # clustering: losing months concentration
    lm = trades[trades[net] < 0].assign(month=lambda d: d["exit_ts"].dt.to_period("M"))
    cnt = lm.groupby("month").size()
    ld["clustering_months_with_losses_gini_like"] = {
        "max_losses_single_month": int(cnt.max()) if len(cnt) else 0,
        "months_with_3plus_losses": int((cnt >= 3).sum()) if len(cnt) else 0,
    }
    jdump(ld, "loss_dynamics.json")

    # ── Phase 7: exit attribution + premature exits ────────────────
    ea = []
    dirsign = trades["direction"].map({"LONG": 1, "SHORT": -1}).to_numpy()
    exit_loc = close_wide.index.get_indexer(pd.DatetimeIndex(trades["exit_ts"]))
    for reason, g in trades.groupby("exit_reason"):
        locs = exit_loc[g.index.to_numpy()]
        opp20 = []
        for i, xl in zip(g.index, locs):
            if xl < 0 or xl + 20 >= len(close_wide):
                continue
            s = g.loc[i, "symbol"]
            px0 = close_wide[s].iloc[xl]
            px20 = close_wide[s].iloc[xl + 20]
            opp20.append(dirsign[g.index.get_loc(i)] * (px20 / px0 - 1))
        ea.append(
            {
                "exit_reason": reason,
                "n": int(len(g)),
                "avg_net": float(g[net].mean()),
                "median_net": float(g[net].median()),
                "pct_profitable": float((g[net] > 0).mean()),
                "mfe_R_median": float(g["mfe_R"].median()),
                "mae_R_median": float(g["mae_R"].median()),
                "hold_days_median": float(g["holding_trading_days"].median()),
                "total_contribution": float(g[net].sum()),
                "post_exit_20b_dir_resumption_mean": float(np.nanmean(opp20))
                if opp20
                else None,
                "post_exit_missed_move_share_gt_halfR": float(
                    np.mean(
                        [
                            o > 0.5 * g["R_price_space"].iloc[k]
                            for k, o in enumerate(opp20)
                        ]
                    )
                )
                if opp20
                else None,
            }
        )
    jdump({"by_reason": ea}, "exit_attribution.json")

    print("\nheadline:")
    print(
        "  n:",
        len(trades),
        "| net expectancy/trade:",
        round(trades[net].mean(), 5),
        "| win rate:",
        round((trades[net] > 0).mean(), 4),
    )
    print(
        "  monotone signal buckets:",
        ss["monotonicity_holds"],
        ss["monotonicity_expectancy_spearman"],
    )
    print(
        "  prob(+1R):",
        round(eq["mfe_mae"]["prob_reach_plus_1R"], 3),
        "| prob(-1R):",
        round(eq["mfe_mae"]["prob_reach_minus_1R"], 3),
    )


if __name__ == "__main__":
    main()
