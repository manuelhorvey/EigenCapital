"""Trade analysis utilities for backtesting."""

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REGIME_GEOM = {
    "low": {"sl": 1.0, "tp": 2.0},
    "mid": {"sl": 1.5, "tp": 2.5},
    "high": {"sl": 2.0, "tp": 3.0},
}

DEF_SL = 1.5
DEF_TP = 2.5


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _signals(proba, thr=0.45):
    """Convert probability array to signal DataFrame.

    proba is (n, 3) with columns [short, neutral, long].
    Returns DataFrame with columns: signal (0=short, 1=neutral, 2=long),
    pl (prob_long), ps (prob_short).
    """
    n = len(proba)
    short_proba = proba[:, 0]
    long_proba = proba[:, 2]

    signals = np.full(n, 1, dtype=int)  # default neutral

    short_active = short_proba > thr
    long_active = long_proba > thr
    conflict = short_active & long_active

    # Non-conflicting short signals
    signals[short_active & ~conflict] = 0
    # Non-conflicting long signals
    signals[long_active & ~conflict] = 2
    # Conflicting -> neutral
    signals[conflict] = 1

    return pd.DataFrame(
        {"signal": signals, "pl": long_proba, "ps": short_proba},
    )


def aggregate(trades):
    """Aggregate trade statistics from a list of trade dicts.

    Computes overall metrics (win rate, profit factor, R-multiples,
    MAE/MFE, efficiency), per-asset breakdown, duration by exit reason,
    and duration distribution (bucketed).

    Args:
        trades: List of dicts, each expected to contain: asset, return,
            r_multiple, mae_r, mfe_r, exit_reason, bars_held, entry_date.

    Returns:
        dict with keys: n_trades, n_assets, overall (aggregate metrics),
        by_asset, duration_by_reason, duration_distribution.
        Returns {"n_trades": 0} for empty input.
    """
    if not trades:
        return {"n_trades": 0}

    n_trades = len(trades)
    assets = set(t["asset"] for t in trades)
    n_assets = len(assets)

    returns = np.array([t.get("return", 0.0) for t in trades])
    r_multiples = np.array([t.get("r_multiple", 0.0) for t in trades])
    wins = returns > 0
    losses = returns <= 0
    n_wins = int(wins.sum())
    n_losses = int(losses.sum())

    total_return = float(returns.sum())
    win_rate = n_wins / n_trades if n_trades > 0 else 0.0
    loss_rate = n_losses / n_trades if n_trades > 0 else 0.0
    avg_win = float(returns[wins].mean()) if n_wins > 0 else 0.0
    avg_loss = float(returns[losses].mean()) if n_losses > 0 else 0.0
    profit_factor = abs(avg_win * n_wins / (avg_loss * n_losses)) if n_losses > 0 and avg_loss != 0 else float("inf")
    avg_r = float(r_multiples.mean())
    total_r = float(r_multiples.sum())
    avg_mae_r = float(np.mean([t.get("mae_r", 0.0) for t in trades]))
    avg_mfe_r = float(np.mean([t.get("mfe_r", 0.0) for t in trades]))
    efficiency = avg_r / avg_mae_r if avg_mae_r > 0 else 0.0

    overall = {
        "n_trades": n_trades,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "total_return": total_return,
        "avg_return": total_return / n_trades if n_trades > 0 else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "total_r": total_r,
        "avg_mae_r": avg_mae_r,
        "avg_mfe_r": avg_mfe_r,
        "efficiency": efficiency,
    }

    # By asset
    by_asset = {}
    for asset in sorted(assets):
        asset_trades = [t for t in trades if t["asset"] == asset]
        asset_returns = np.array([t.get("return", 0.0) for t in asset_trades])
        asset_wins = (asset_returns > 0).sum()
        asset_n = len(asset_trades)
        by_asset[asset] = {
            "n_trades": asset_n,
            "win_rate": asset_wins / asset_n if asset_n > 0 else 0.0,
            "total_return": float(asset_returns.sum()),
        }

    # Duration by reason
    duration_by_reason = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        bars = t.get("bars_held", 0)
        if reason not in duration_by_reason:
            duration_by_reason[reason] = []
        duration_by_reason[reason].append(bars)
    duration_by_reason = {k: float(np.mean(v)) for k, v in duration_by_reason.items()}

    # Duration distribution
    duration_distribution = {}
    for t in trades:
        bars = t.get("bars_held", 0)
        if bars <= 3:
            bucket = "1-3d"
        elif bars <= 7:
            bucket = "4-7d"
        elif bars <= 14:
            bucket = "8-14d"
        elif bars <= 30:
            bucket = "15-30d"
        else:
            bucket = "30d+"
        if bucket not in duration_distribution:
            duration_distribution[bucket] = {"count": 0, "wins": 0, "losses": 0}
        duration_distribution[bucket]["count"] += 1
        if t.get("return", 0) > 0:
            duration_distribution[bucket]["wins"] += 1
        else:
            duration_distribution[bucket]["losses"] += 1

    return {
        "n_trades": n_trades,
        "n_assets": n_assets,
        "overall": overall,
        "by_asset": by_asset,
        "duration_by_reason": duration_by_reason,
        "duration_distribution": duration_distribution,
    }


def flip_quality(trades):
    """Analyze quality of signal flips.

    For each trade exited due to a signal flip (exit_reason == "signal_flip"),
    computes the flip's R-multiple and the subsequent trade's R-multiple
    to assess whether flips are predictive or destructive.

    Args:
        trades: List of trade dicts sorted chronologically, each containing
            exit_reason, r_multiple, entry_date.

    Returns:
        dict with keys: total_flips_analyzed, avg_r (flip R),
        avg_next_r (subsequent trade R), next_positive (count),
        next_positive_rate.
        Returns empty dict if no flips found.

    Raises:
        KeyError: If trades list is empty.
    """
    if not trades:
        raise KeyError("No trades to analyze")

    total_flips = 0
    flip_r_values = []
    next_r_values = []
    next_positives = 0
    total_next = 0

    sorted_trades = sorted(trades, key=lambda t: t.get("entry_date", ""))
    for i, t in enumerate(sorted_trades):
        if t.get("exit_reason") == "signal_flip":
            total_flips += 1
            flip_r_values.append(t.get("r_multiple", 0.0))
            if i + 1 < len(sorted_trades):
                next_t = sorted_trades[i + 1]
                next_r = next_t.get("r_multiple", 0.0)
                next_r_values.append(next_r)
                if next_r > 0:
                    next_positives += 1
                total_next += 1

    if total_flips == 0:
        return {}

    return {
        "total_flips_analyzed": total_flips,
        "avg_r": float(np.mean(flip_r_values)) if flip_r_values else 0.0,
        "avg_next_r": float(np.mean(next_r_values)) if next_r_values else 0.0,
        "next_positive": next_positives,
        "next_positive_rate": next_positives / total_next if total_next > 0 else 0.0,
    }


def paper_stats(trades):
    """Compute paper trading style statistics from a list of trade dicts.

    Reports trade count, win rate, TP rate, SL rate, average return,
    and per-asset breakdown. Supports both "reason" and "exit_reason"
    keys for exit reason detection.

    Args:
        trades: List of dicts with "return", "reason" or "exit_reason",
            and "asset" keys.

    Returns:
        dict with keys: n_trades, win_rate, tp_rate, sl_rate,
        avg_return, by_asset (mapping asset -> {n_trades, win_rate}).
        Returns empty dict for empty input.
    """
    if not trades:
        return {}

    n_trades = len(trades)
    returns = []
    reasons = []
    by_asset = {}

    for t in trades:
        r = t.get("return", 0.0)
        returns.append(r)
        reason = t.get("reason") or t.get("exit_reason", "unknown")
        reasons.append(reason)
        asset = t.get("asset", "unknown")
        if asset not in by_asset:
            by_asset[asset] = {"n": 0, "wins": 0}
        by_asset[asset]["n"] += 1
        if r > 0:
            by_asset[asset]["wins"] += 1

    returns_arr = np.array(returns)
    n_wins = int((returns_arr > 0).sum())
    n_tp = sum(1 for r in reasons if r in ("tp", "take_profit"))
    n_sl = sum(1 for r in reasons if r in ("sl", "stop_loss"))

    stats = {
        "n_trades": n_trades,
        "win_rate": n_wins / n_trades if n_trades > 0 else 0.0,
        "tp_rate": n_tp / n_trades if n_trades > 0 else 0.0,
        "sl_rate": n_sl / n_trades if n_trades > 0 else 0.0,
        "avg_return": float(returns_arr.mean()),
        "by_asset": {
            a: {
                "n_trades": v["n"],
                "win_rate": v["wins"] / v["n"] if v["n"] > 0 else 0.0,
            }
            for a, v in by_asset.items()
        },
    }
    return stats


def fetch_ohlcv(*args, **kwargs):
    """Fetch OHLCV data. Placeholder."""
    raise NotImplementedError("Reimplement from data_fetch if needed")


def load_macro(*args, **kwargs):
    """Load macro data. Placeholder."""
    raise NotImplementedError("Reimplement from macro_loader if needed")


def _simulate(*args, **kwargs):
    """Simulate trading. Placeholder."""
    raise NotImplementedError("Reimplement if needed")
