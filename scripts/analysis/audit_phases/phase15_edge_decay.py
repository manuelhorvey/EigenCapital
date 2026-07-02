"""Phase 15 — Edge Decay Analysis.

Determines when predictive edge disappears:
  - Rolling win rate / expectancy across trade sequence
  - Finds point where rolling expectancy turns negative
  - Tests whether force-closing at edge decay point improves PnL
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase15_edge")

ROLLING_WINDOWS = [10, 20, 50]


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 15: Edge decay analysis")

    results: dict[str, Any] = {"per_asset": {}, "portfolio": {}}

    for asset, trades in trades_map.items():
        if len(trades) < 30:
            results["per_asset"][asset] = {"error": "insufficient_trades"}
            continue

        # Sort by entry date
        sorted_trades = sorted(trades, key=lambda t: str(t.get("entry_date", "")))
        rs = np.array([t["r_multiple"] for t in sorted_trades])

        asset_decay: dict = {}

        for window in ROLLING_WINDOWS:
            if len(rs) < window:
                continue

            rolling_wr = np.array([
                (rs[max(0, i - window):i] > 0).mean() * 100
                for i in range(1, len(rs) + 1)
            ])
            rolling_expectancy = np.array([
                rs[max(0, i - window):i].mean()
                for i in range(1, len(rs) + 1)
            ])

            # Find where rolling expectancy turns negative for the first time
            neg_indices = np.where(rolling_expectancy < 0)[0]
            first_neg = int(neg_indices[0]) if len(neg_indices) > 0 else None

            # Find stable periods (consecutive positive expectancy)
            stable_run = 0
            max_stable = 0
            for val in rolling_expectancy:
                if val > 0:
                    stable_run += 1
                    max_stable = max(max_stable, stable_run)
                else:
                    stable_run = 0

            asset_decay[f"window_{window}"] = {
                "first_negative_at_trade": first_neg,
                "pct_negative": round((rolling_expectancy < 0).mean() * 100, 1) if len(rolling_expectancy) > 0 else 0,
                "max_consecutive_positive": max_stable,
                "last_rolling_expectancy": round(float(rolling_expectancy[-1]), 4) if len(rolling_expectancy) > 0 else 0,
                "rolling_wr_last": round(float(rolling_wr[-1]), 1) if len(rolling_wr) > 0 else 0,
            }

        results["per_asset"][asset] = asset_decay

    # Portfolio-level edge decay
    all_rs_list = []
    for ts in trades_map.values():
        for t in ts:
            all_rs_list.append(t["r_multiple"])

    all_rs = np.array(all_rs_list)
    cumulative_r = np.cumsum(all_rs)

    portfolio_decay = {}
    for window in ROLLING_WINDOWS:
        if len(all_rs) < window:
            continue
        rolling_expectancy = np.array([
            all_rs[max(0, i - window):i].mean()
            for i in range(1, len(all_rs) + 1)
        ])
        neg_idx = np.where(rolling_expectancy < 0)[0]
        first_neg = int(neg_idx[0]) if len(neg_idx) > 0 else None

        portfolio_decay[f"window_{window}"] = {
            "first_negative_at_trade": first_neg,
            "pct_negative": round((rolling_expectancy < 0).mean() * 100, 1),
            "last_rolling_expectancy": round(float(rolling_expectancy[-1]), 4),
        }

    results["portfolio"] = portfolio_decay

    return results
