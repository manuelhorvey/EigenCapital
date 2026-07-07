#!/usr/bin/env python3
"""
Audit zero-trade assets in the PnL backtest.

The walk-forward signal parquets commit to a single decision threshold:
BUY if p_long > 0.575, SELL if p_long < 0.425 (ensemble_threshold=0.15
in ``scripts/backtest/walk_forward_backtest.py``).  Assets whose
out-of-sample p_long never crosses 0.575 therefore produce zero trades
in the backtest even if their production ``min_confidence`` is 0.40.

This script:

  1. Identifies every asset that produced 0 non-flat signals in the
     tag-matched parquet set (same discovery rules as backtest_pnl.py).
  2. Reports p_long distribution stats and rank-IC vs label.
  3. Sweeps *absolute* decision thresholds from 0.40 to 0.60 — for each
     threshold computes would-have-been n_trades, win_rate, total_R, and
     Sharpe using the *same* triple-barrier semantics as backtest_pnl.py.
     Threshold is interpreted as: BUY if p_long > T, SELL if p_long <
     (1-T), else FLAT.  So T=0.575 reproduces the WF default.
  4. Cross-references each asset's production min_confidence to surface
     the gap between backtest threshold and live threshold.
  5. Classifies each asset.

All operations are read-only (parquets + config).  No model training,
no live inference, no state mutation.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/audit_zero_trade_assets.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/audit_zero_trade_assets.py --tag base
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/audit_zero_trade_assets.py \\
        --thresholds 0.40,0.45,0.50,0.55,0.575
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/audit_zero_trade_assets.py \\
        --json out/zero_trade_audit.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from scripts.backtest.backtest_pnl import (
    WALKDIR,
    _asset_pt_sl_from_config,
    compute_trade_pnl,
)

logger = logging.getLogger("audit_zero_trade")

DEFAULT_THRESHOLDS = (0.40, 0.45, 0.50, 0.52, 0.55, 0.575, 0.60)
WF_DEFAULT_THRESHOLD = 0.575  # ensemble_threshold=0.15 → BUY > 0.575, SELL < 0.425

SELL_ONLY_ASSETS: frozenset[str] = frozenset({"CADCHF", "NZDCHF", "EURAUD"})


def _load_min_confidence() -> dict[str, float]:
    """Return per-asset production min_confidence as absolute values."""
    from paper_trading.config_manager import get_config

    cfg = get_config()
    default_mc = float(cfg.defaults.get("min_confidence", 55.0))
    # Config min_confidence is on a 0-100 percent scale (live
    # ``decision.confidence`` is computed as ``max(prob_long, prob_short)
    # * 100`` — see signals/paper_signal_adapter.py:27).  Convert to 0-1
    # to compare directly against p_long from the walk-forward parquets.
    out: dict[str, float] = {}
    for name, acfg in cfg.assets.items():
        mc = acfg.get("min_confidence")
        out[name] = (float(mc) / 100.0) if mc is not None else (default_mc / 100.0)
    return out


def _signals_from_p_long(p_long: np.ndarray, threshold: float) -> np.ndarray:
    """Build signals from absolute threshold T using live engine semantics.

    Live engine (``paper_trading/ops/wrappers.py:37``, ``signals/paper_signal_adapter.py``):
      confidence = max(prob_long, prob_short)
      side       = "BUY" if prob_long > prob_short else "SELL"
      trade fires if confidence >= min_confidence

    For a binary XGBoost ``prob_long = p_long`` and ``prob_short = 1 - p_long``.
    So:

      T <= 0.5  → side = sign(p_long - 0.5), trades whenever p_long != 0.5
                  (very permissive; fundamentally "trade if model has any
                  directional view at all")
      T >  0.5  → BUY  if p_long >= T
                  SELL if p_long <= 1 - T
                  FLAT otherwise
                  (matches walk_forward_backtest.py:230–234 with T = 0.5 +
                  ensemble_threshold/2)

    This is consistent with both the live ``decision_pipeline.py`` gate
    (``confidence < min_conf``) and the walk-forward parquet signal
    semantics — they are the same rule, just expressed differently.
    """
    sig = np.zeros(len(p_long), dtype=int)
    if threshold <= 0.5:
        # Permissive: trade the side you lean toward.
        buy_mask = p_long > 0.5
        sell_mask = p_long < 0.5
    else:
        buy_mask = p_long >= threshold
        sell_mask = p_long <= 1.0 - threshold
    sig[buy_mask] = 1
    sig[sell_mask] = -1
    return sig


def _pnl_at_threshold(df: pd.DataFrame, tp: float, sl: float, threshold: float, sell_only: bool) -> dict:
    """Compute PnL stats when ``df`` is re-thresholded at ``threshold``."""
    empty = {
        "n_trades": 0,
        "n_buy": 0,
        "n_sell": 0,
        "win_rate": 0.0,
        "total_R": 0.0,
        "sharpe": 0.0,
    }
    if "p_long" not in df.columns or "label" not in df.columns:
        return empty

    p_long = df["p_long"].astype(float).values
    signals = _signals_from_p_long(p_long, threshold)
    labels = df["label"].astype(int).values

    if sell_only:
        signals = np.where(signals == 1, 0, signals)

    n_buy = int((signals == 1).sum())
    n_sell = int((signals == -1).sum())
    n_trades = n_buy + n_sell
    if n_trades == 0:
        return empty

    r_values = np.array(
        [compute_trade_pnl(int(sig_i), int(lbl_i), tp, sl) for sig_i, lbl_i in zip(signals, labels)],
        dtype=float,
    )
    nonzero = r_values[r_values != 0]
    if len(nonzero) < 2:
        return {
            "n_trades": n_trades,
            "n_buy": n_buy,
            "n_sell": n_sell,
            "win_rate": round(float((r_values > 0).sum()) / n_trades, 4),
            "total_R": round(float(r_values.sum()), 2),
            "sharpe": float("nan"),
        }

    std = float(nonzero.std())
    # Numerically tiny std (all wins hit the same +tp or all losses hit the
    # same -sl) makes Sharpe explode to +inf or -inf.  Report NaN instead —
    # the metric is undefined in this degenerate regime, not "inf".
    sharpe = float("nan") if not math.isfinite(std) or std < 1e-9 else float(nonzero.mean() / std * np.sqrt(252))

    wins = int((r_values > 0).sum())
    return {
        "n_trades": n_trades,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "win_rate": round(wins / n_trades, 4),
        "total_R": round(float(r_values.sum()), 2),
        "sharpe": round(sharpe, 4) if math.isfinite(sharpe) else float("nan"),
    }


def _p_long_stats(df: pd.DataFrame) -> dict:
    if "p_long" not in df.columns or len(df) == 0:
        return {"obs": 0}
    p = df["p_long"].astype(float)
    return {
        "obs": int(len(p)),
        "min": round(float(p.min()), 4),
        "max": round(float(p.max()), 4),
        "mean": round(float(p.mean()), 4),
        "std": round(float(p.std()), 4),
        "p05": round(float(p.quantile(0.05)), 4),
        "p95": round(float(p.quantile(0.95)), 4),
        "above_05": int((p > 0.5).sum()),
        "below_05": int((p < 0.5).sum()),
    }


def _rank_ic(df: pd.DataFrame) -> float:
    if "p_long" not in df.columns or "label" not in df.columns or len(df) < 20:
        return float("nan")
    rho, _ = spearmanr(df["p_long"].astype(float), df["label"].astype(float))
    return float(rho) if np.isfinite(rho) else float("nan")


def _classify(asset: str, stats: dict, sweep: list[dict], prod_mc: float) -> str:
    """Classify what's wrong with this asset.

    Returns one of:
      RECOVERABLE_RETHRESH — production min_confidence itself (the row
                              marked `*` in the sweep) yields >=10 trades
                              with a non-degenerate outcome.  Backtest is
                              silently under-counting what live would do.
                              Switch backtest to per-asset thresholds.
      INERT_RANGE          — some swept threshold yields >=10 trades but
                              the production threshold itself does not.
                              Could be made to trade by lowering
                              ``min_confidence`` in production, but doing
                              so is a real risk decision with marginal
                              conviction behind each trade.
      INERT_MODEL          — even the loosest swept threshold (T <= 0.5,
                              the "trade on any view" floor) yields <10
                              trades.  The model itself is stuck; only
                              retraining or feature R&D will recover.
      SELL_ONLY_GAP        — production threshold yields n_buy>0 but they
                              are filtered by SELL_ONLY; n_sell stays
                              below 10.  Expected for the 3 SELL_ONLY
                              assets; not a bug.
      NO_DATA / EMPTY_PARQUET — discovered but no OOS rows.
    """
    if stats.get("obs", 0) == 0:
        return "NO_DATA"

    prod_row = next((r for r in sweep if r.get("is_prod_threshold")), None)
    if prod_row is None:
        return "INERT_MODEL"

    has_prod_trades = prod_row["n_trades"] >= 10
    has_viable_loose = any(r["n_trades"] >= 10 for r in sweep)

    if has_prod_trades:
        has_buy = prod_row["n_buy"] > 0
        has_sell = prod_row["n_sell"] > 0
        if has_buy and not has_sell and asset in SELL_ONLY_ASSETS:
            return "SELL_ONLY_GAP"
        return "RECOVERABLE_RETHRESH"

    if has_viable_loose:
        return "INERT_RANGE"

    return "INERT_MODEL"


def audit(tag: str, thresholds: list[float], sell_only: bool) -> dict:
    """Return full audit dict (per-asset + summary)."""
    pt_sl = _asset_pt_sl_from_config()
    prod_mc = _load_min_confidence()

    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    if not parquets:
        parquets = sorted(WALKDIR.glob("*_wf_signals.parquet"))
        if parquets:
            logger.info("No tagged parquets — using tag-less fallback")
    if not parquets:
        logger.error("No signal parquets found in %s", WALKDIR)
        sys.exit(1)

    per_asset: dict[str, dict] = {}
    for pq in parquets:
        asset = pq.stem.split("_wf_signals")[0]
        if asset not in pt_sl:
            continue
        tp, sl = pt_sl[asset]

        df = pd.read_parquet(pq)
        if df.empty:
            per_asset[asset] = {
                "status": "EMPTY_PARQUET",
                "tp": tp,
                "sl": sl,
                "classification": "NO_DATA",
            }
            continue

        n_trades_in_parquet = int((df["signal"] != 0).sum() if "signal" in df.columns else 0)
        if n_trades_in_parquet > 0:
            continue

        stats = _p_long_stats(df)
        ic = _rank_ic(df)
        is_sell_only = sell_only and asset in SELL_ONLY_ASSETS

        # Make sure the production min_confidence itself is in the sweep.
        sweep_thresholds = list(dict.fromkeys(thresholds + [prod_mc.get(asset, 55.0)]))
        sweep_thresholds.sort()
        sweep = []
        for thr in sweep_thresholds:
            pnl = _pnl_at_threshold(df, tp, sl, thr, sell_only=is_sell_only)
            pnl["threshold_abs"] = round(float(thr), 4)
            pnl["is_prod_threshold"] = abs(thr - prod_mc.get(asset, 55.0)) < 1e-6
            sweep.append(pnl)

        prod = prod_mc.get(asset, 55.0)
        classification = _classify(asset, stats, sweep, prod)

        per_asset[asset] = {
            "tp": tp,
            "sl": sl,
            "tp_sl_ratio": round(tp / sl, 3) if sl > 0 else float("inf"),
            "prod_min_confidence": prod,
            "wf_default_threshold": WF_DEFAULT_THRESHOLD,
            "sell_only": is_sell_only,
            "p_long_stats": stats,
            "rank_ic": round(ic, 4) if np.isfinite(ic) else None,
            "n_trades_in_parquet": 0,
            "sweep": sweep,
            "classification": classification,
        }

    return {
        "tag": tag,
        "wf_default_threshold": WF_DEFAULT_THRESHOLD,
        "thresholds_swept": list(thresholds),
        "prod_min_confidences": prod_mc,
        "n_zero_trade_assets": len(per_asset),
        "per_asset": per_asset,
    }


def _fmt_sharpe(x: float) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "  NaN"
    return f"{x:7.2f}"


def _print_report(report: dict) -> None:
    print("=" * 80)
    print("ZERO-TRADE ASSET AUDIT")
    print("=" * 80)
    print()
    print(f"  Tag: {report['tag']}   WF default threshold: {report['wf_default_threshold']}")
    print(f"  Zero-trade assets: {report['n_zero_trade_assets']}")
    print(f"  Thresholds swept: {report['thresholds_swept']}")
    print()
    print("  Live-engine semantics: trade fires when max(p_long, 1-p_long)")
    print("    >= T. Side is BUY if p_long > 0.5 else SELL.")
    print("    T > 0.5  → BUY if p_long >= T, SELL if p_long <= 1-T, else FLAT")
    print("    T <= 0.5 → trades whenever p_long != 0.5 (no conviction floor)")
    print()
    print("  Legend (HIGH-value rows are production threshold):")
    print("    * = production min_confidence for this asset")
    print()

    per_asset = report["per_asset"]
    if not per_asset:
        print("  No zero-trade assets — everything generated at least one trade.")
        return

    order = ["RECOVERABLE_RETHRESH", "SELL_ONLY_GAP", "INERT_RANGE", "INERT_MODEL", "NO_DATA"]
    items = sorted(
        per_asset.items(),
        key=lambda kv: (
            order.index(kv[1].get("classification", "INERT_MODEL")) if kv[1].get("classification") in order else 99,
            kv[0],
        ),
    )

    for asset, info in items:
        print("-" * 80)
        print(f"  {asset}   [{info.get('classification', 'INERT_MODEL')}]")
        print()
        if info.get("status") == "EMPTY_PARQUET":
            print("    empty parquet — no OOS predictions written")
            continue

        print(
            f"    tp/sl={info['tp']}/{info['sl']} (R:R={info['tp_sl_ratio']})   "
            f"prod min_conf={info['prod_min_confidence']}   "
            f"sell_only={info['sell_only']}"
        )
        s = info["p_long_stats"]
        print(
            f"    p_long: obs={s['obs']} min={s['min']} max={s['max']} "
            f"mean={s['mean']} std={s['std']} p05={s['p05']} p95={s['p95']}"
        )
        print(f"            above_0.5={s['above_05']}  below_0.5={s['below_05']}   rank_IC={info['rank_ic']}")
        print()
        print(
            f"    {'thr':>6}  {'n_trades':>8}  {'n_buy':>5}  {'n_sell':>6}  "
            f"{'win_rate':>8}  {'total_R':>8}  {'sharpe':>7}"
        )
        for row in info["sweep"]:
            marker = " *" if row.get("is_prod_threshold") else "  "
            sharpe_disp = _fmt_sharpe(row["sharpe"])
            print(
                f"   {marker} {row['threshold_abs']:>6.3f}  "
                f"{row['n_trades']:>8d}  {row['n_buy']:>5d}  {row['n_sell']:>6d}  "
                f"{row['win_rate']:>8.3f}  {row['total_R']:>8.2f}  {sharpe_disp}"
            )
        print()

    print("=" * 80)
    print("CLASSIFICATION SUMMARY")
    print("=" * 80)
    counts: dict[str, int] = {}
    for info in per_asset.values():
        c = info.get("classification", "INERT_MODEL")
        counts[c] = counts.get(c, 0) + 1
    for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {cls:25s}  {n}")
    print()
    print("  RECOVERABLE_RETHRESH — at the production min_confidence itself")
    print("                          this asset produces >=10 trades; backtest")
    print("                          simply used 0.575.  Switch backtest to")
    print("                          per-asset thresholds or regenerate parquets")
    print("                          at the production value to capture the")
    print("                          same trade flow live would have.")
    print("  INERT_RANGE          — some swept threshold yields >=10 trades")
    print("                          but the production threshold itself does")
    print("                          not.  Could be unblocked by lowering")
    print("                          ``min_confidence`` but doing so is a real")
    print("                          risk decision with marginal conviction")
    print("                          behind every trade it would unlock.")
    print("  INERT_MODEL          — even the loosest swept threshold (T<=0.5,")
    print("                          'trade on any view') yields <10 trades.  The")
    print("                          model itself is stuck near 0.5; retraining")
    print("                          or feature R&D is the only path.")
    print("  SELL_ONLY_GAP        — production threshold yields n_buy>0 but")
    print("                          they're filtered by SELL_ONLY.  Expected")
    print("                          for the 3 SELL_ONLY assets; not a bug.")
    print("  NO_DATA              — empty / missing parquet.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="base", help="Signal parquet suffix")
    parser.add_argument(
        "--thresholds",
        default="0.40,0.45,0.50,0.52,0.55,0.575,0.60",
        help="Comma-separated absolute p_long thresholds to sweep (e.g. 0.40,0.55)",
    )
    parser.add_argument("--no-sell-only", action="store_true", help="Disable SELL_ONLY override")
    parser.add_argument("--json", default=None, help="Write full report JSON to this path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    thresholds = [float(t.strip()) for t in args.thresholds.split(",") if t.strip()]

    logger.info(
        "Auditing zero-trade assets (tag=%s, thresholds=%s, sell_only=%s)",
        args.tag,
        thresholds,
        not args.no_sell_only,
    )

    report = audit(args.tag, thresholds, sell_only=not args.no_sell_only)
    _print_report(report)

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def _sanitize(o):
            if isinstance(o, float) and not math.isfinite(o):
                return None
            return o

        with out_path.open("w") as f:
            json.dump(report, f, indent=2, default=_sanitize)
        logger.info("Report JSON -> %s", out_path)


if __name__ == "__main__":
    main()
