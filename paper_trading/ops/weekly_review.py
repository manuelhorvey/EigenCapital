import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pandas as pd
import pytz

from paper_trading.state_store import StateStore

ET = pytz.timezone("US/Eastern")

logger = logging.getLogger("eigencapital.weekly_review")

WINDOW_DAYS = 7


def _week_label(d: date) -> str:
    start = d - timedelta(days=WINDOW_DAYS)
    return f"{start.isoformat()} – {d.isoformat()}"


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def _compute_trade_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "n_trades": 0,
            "total_pnl": 0.0,
            "total_return_pct": 0.0,
            "win_rate": 0.0,
            "tp_rate": 0.0,
            "sl_rate": 0.0,
            "signal_flip_rate": 0.0,
            "profit_factor": None,
            "avg_r": 0.0,
            "best_r_multiple": 0.0,
            "worst_r_multiple": 0.0,
        }

    returns = df["return"].fillna(0.0)
    total_pnl = float(returns.sum())
    total_return_pct = float(returns.mean() * len(df))

    reasons = df["reason"].str.lower()
    n_tp = int((reasons == "tp").sum())
    n_sl = int((reasons == "sl").sum())
    n_flip = int((reasons == "signal_flip").sum())

    winners = returns[returns > 0]
    losers = returns[returns < 0]
    n = len(df)
    win_rate = _safe_div(len(winners), n) or 0.0
    tp_rate = _safe_div(n_tp, n) or 0.0
    sl_rate = _safe_div(n_sl, n) or 0.0
    flip_rate = _safe_div(n_flip, n) or 0.0

    gross_profit = float(winners.sum()) if not winners.empty else 0.0
    gross_loss = float(abs(losers.sum())) if not losers.empty else 0.0
    profit_factor = _safe_div(gross_profit, gross_loss) if gross_loss > 0 else None

    avg_r = float(returns.mean())
    best_r = float(returns.max())
    worst_r = float(returns.min())

    return {
        "n_trades": n,
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 4),
        "win_rate": round(win_rate, 4),
        "tp_rate": round(tp_rate, 4),
        "sl_rate": round(sl_rate, 4),
        "signal_flip_rate": round(flip_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "avg_r": round(avg_r, 4),
        "best_r_multiple": round(best_r, 4),
        "worst_r_multiple": round(worst_r, 4),
    }


def _exit_reason_breakdown(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"SL": 0, "TP": 0, "BREAKEVEN": 0, "FLIP": 0, "EXPIRY": 0, "MANUAL": 0, "other": 0}
    reasons = df["reason"].str.upper()
    sl = int((reasons == "SL").sum())
    tp = int((reasons == "TP").sum())
    be = int((reasons == "BREAKEVEN").sum())
    flip = int((reasons == "FLIP").sum())
    expiry = int((reasons == "EXPIRY").sum())
    manual = int((reasons == "MANUAL").sum())
    other = int((~reasons.isin(["SL", "TP", "BREAKEVEN", "FLIP", "EXPIRY", "MANUAL", "TRAILING_SL"])).sum())
    trailing_sl = int((reasons == "TRAILING_SL").sum())
    return {
        "SL": sl,
        "TP": tp,
        "BREAKEVEN": be,
        "FLIP": flip,
        "EXPIRY": expiry,
        "MANUAL": manual,
        "TRAILING_SL": trailing_sl,
        "other": other,
    }


def _top_trades(df: pd.DataFrame, field: str = "return", n: int = 3, ascending: bool = False) -> list[dict]:
    if df.empty:
        return []
    sorted_df = df.sort_values(field, ascending=ascending).head(n)
    return json.loads(sorted_df.to_json(orient="records", default_handler=str))


def _per_asset_metrics(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    rows = []
    for asset, group in df.groupby("asset"):
        m = _compute_trade_metrics(group)
        rows.append(
            {
                "asset": asset,
                "n_trades": m["n_trades"],
                "win_rate": m["win_rate"],
                "tp_rate": m["tp_rate"],
                "sl_rate": m["sl_rate"],
                "avg_r": m["avg_r"],
                "profit_factor": m["profit_factor"],
                "pnl": m["total_pnl"],
            }
        )
    return rows


def _boundary_dates() -> tuple[date, date, date]:
    today = date.today()
    week_start = today - timedelta(days=WINDOW_DAYS)
    prior_week_start = week_start - timedelta(days=WINDOW_DAYS)
    return prior_week_start, week_start, today


def _stop_out_summary(state: dict, week_start: str) -> dict:
    assets = state.get("assets", {})
    count = 0
    in_cooldown = []
    for name, adata in assets.items():
        last_date = adata.get("stop_out_last_date")
        if last_date and last_date >= week_start:
            count += 1
            in_cooldown.append(name)
    return {
        "stop_out_cooldowns_triggered": count,
        "estimated_churn_prevented": count,
        "assets_in_cooldown": in_cooldown,
    }


def _governance_summary(state: dict) -> dict:
    assets = state.get("assets", {})
    halted = []
    validity_counts: dict[str, int] = {}
    for name, adata in assets.items():
        if adata.get("halt", {}).get("halted", False):
            halted.append(name)
        v = adata.get("validity_state", "YELLOW")
        validity_counts[v] = validity_counts.get(v, 0) + 1
    most_common = max(validity_counts, key=validity_counts.get) if validity_counts else "YELLOW"
    return {
        "halted_assets": halted,
        "most_common_validity": most_common,
    }


def _regime_correlation(df: pd.DataFrame, state: dict) -> list[dict]:
    assets = state.get("assets", {})
    regimes: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        asset_name = row.get("asset")
        adata = assets.get(asset_name, {})
        regime = adata.get("narrative_regime") or "UNKNOWN"
        regimes.setdefault(regime, []).append(row)

    results = []
    for regime, rows in regimes.items():
        n = len(rows)
        wins = sum(1 for r in rows if r.get("return", 0) is not None and float(r.get("return", 0)) > 0)
        sl_count = sum(1 for r in rows if str(r.get("reason", "")).lower() == "sl")
        results.append(
            {
                "regime": regime,
                "n_trades": n,
                "win_rate": round(_safe_div(wins, n) or 0.0, 4),
                "sl_rate": round(_safe_div(sl_count, n) or 0.0, 4),
            }
        )
    return results


def compute_weekly_review(store: StateStore) -> dict:
    today = date.today()
    prior_week_start, week_start, _ = _boundary_dates()
    week_start_str = week_start.isoformat()
    prior_week_start_str = prior_week_start.isoformat()

    this_week_df = store.read_trades_since(week_start_str)
    prior_week_full_df = store.read_trades_since(prior_week_start_str)

    if not prior_week_full_df.empty:
        prior_week_df = prior_week_full_df[
            (prior_week_full_df["exit_date"] >= prior_week_start_str)
            & (prior_week_full_df["exit_date"] < week_start_str)
        ].copy()
    else:
        prior_week_df = prior_week_full_df

    summary = _compute_trade_metrics(this_week_df)
    prior_summary = _compute_trade_metrics(prior_week_df)

    if prior_summary["n_trades"] > 0 and summary["n_trades"] > 0:
        vs_prior = {
            "pnl_change": round(summary["total_pnl"] - prior_summary["total_pnl"], 2),
            "win_rate_change": round(summary["win_rate"] - prior_summary["win_rate"], 4),
            "sl_rate_change": round(summary["sl_rate"] - prior_summary["sl_rate"], 4),
            "tp_rate_change": round(summary["tp_rate"] - prior_summary["tp_rate"], 4),
        }
    else:
        vs_prior = None

    snapshot = store.load_snapshot()
    if snapshot is not None:
        state = {
            "assets": (asdict(snapshot).get("assets") or {}),
            "portfolio": (asdict(snapshot).get("portfolio") or {}),
        }
    else:
        state = {"assets": {}, "portfolio": {}}

    result = {
        "week_label": _week_label(today),
        "generated_at": datetime.now(tz=ET).isoformat(),
        "summary": summary,
        "by_asset": _per_asset_metrics(this_week_df),
        "top_winners": _top_trades(this_week_df, "return", 3, ascending=False),
        "top_losers": _top_trades(this_week_df, "return", 3, ascending=True),
        "exit_reason_breakdown": _exit_reason_breakdown(this_week_df),
        "stop_out_cooldowns": _stop_out_summary(state, week_start_str),
        "governance_summary": _governance_summary(state),
        "regime_correlation": _regime_correlation(this_week_df, state),
        "vs_prior_week": vs_prior,
    }

    return result
