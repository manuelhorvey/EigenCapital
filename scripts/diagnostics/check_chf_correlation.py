#!/usr/bin/env python3
"""CHF-cluster correlation check — verify independence assumption.

The SELL_ONLY filter creates 4 SELL-on-CHF positions (CADCHF, NZDCHF,
USDCHF, EURCHF).  All 4 go long CHF when SELL-ing.  This script checks
whether they are genuinely independent bets or a single leveraged CHF
strength position wearing four tickers.

Measures:
  1. Pairwise return correlations of the CHF crosses (daily)
  2. Concurrent active signal overlap (are they trading same direction?)
  3. Worst-case drawdown if all 4 lose simultaneously
  4. Frequency of 3+ losing days in the CHF cluster

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/check_chf_correlation.py

Output: prints summary to terminal.
"""

from __future__ import annotations

import logging
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent))

from features.data_fetch import fetch_asset_data
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chf_corr")

BASE = Path(__file__).resolve().parent.parent

CHF_CLUSTER = [
    ("CADCHF", "CADCHF=X"),
    ("NZDCHF", "NZDCHF=X"),
    ("USDCHF", "USDCHF=X"),
    ("EURCHF", "EURCHF=X"),
]


def main():
    close_prices = {}
    for name, ticker in CHF_CLUSTER:
        logger.info("Loading %s (%s)...", name, ticker)
        hist, _, _, _, _, _ = fetch_asset_data(name, ticker)
        if hist.empty:
            logger.warning("%s: no data, skipping", name)
            continue
        # Use the last 2 years if available
        close_prices[name] = hist["close"].dropna().tail(504)

    if len(close_prices) < 2:
        logger.error("Insufficient data for correlation analysis")
        return

    df = pd.DataFrame(close_prices)
    daily_returns = df.pct_change().dropna()

    logger.info("\n=== Pairwise Return Correlations (daily, last ~2yr) ===")
    corr = daily_returns.corr()
    for pair_name in [
        "CADCHF/NZDCHF",
        "CADCHF/USDCHF",
        "CADCHF/EURCHF",
        "NZDCHF/USDCHF",
        "NZDCHF/EURCHF",
        "USDCHF/EURCHF",
    ]:
        a, b = pair_name.split("/")
        if a in corr and b in corr:
            r = corr.loc[a, b]
            logger.info(
                "  %s: r = %.3f  %s", pair_name, r, "HIGH" if abs(r) > 0.7 else "moderate" if abs(r) > 0.5 else "low"
            )

    logger.info("\n=== Mean Pairwise Correlation ===")
    triu = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    mean_corr = triu.stack().mean()
    logger.info("  Mean pairwise r = %.3f", mean_corr)

    logger.info("\n=== Concurrent Direction Agreement ===")
    direction = daily_returns.apply(np.sign)
    agreement = direction.T.corr()
    mean_dir_agree = agreement.where(np.triu(np.ones(agreement.shape), k=1).astype(bool)).stack().mean()
    logger.info("  Mean directional sign agreement = %.3f", mean_dir_agree)

    logger.info("\n=== Worst Concurrent Drawdown ===")
    # Worst N-day period where ALL cross returns are simultaneously negative
    all_negative = (daily_returns < 0).all(axis=1)
    n_concurrent_loss_days = all_negative.sum()
    pct_concurrent_loss = n_concurrent_loss_days / len(daily_returns) * 100
    logger.info(
        "  Days where ALL 4 CHF crosses negative simultaneously: %d (%.1f%%)",
        n_concurrent_loss_days,
        pct_concurrent_loss,
    )

    # Days where 3+ are negative
    three_plus_negative = (daily_returns < 0).sum(axis=1) >= 3
    n_three_plus_loss = three_plus_negative.sum()
    pct_three_plus_loss = n_three_plus_loss / len(daily_returns) * 100
    logger.info("  Days where 3+ CHF crosses negative: %d (%.1f%%)", n_three_plus_loss, pct_three_plus_loss)

    # Worst single-day concurrent loss
    if all_negative.any():
        worst_idx = daily_returns[all_negative].sum(axis=1).idxmin()
        worst_vals = daily_returns.loc[worst_idx]
        logger.info("  Worst concurrent loss day: %s", worst_idx.date())
        for name in CHF_CLUSTER:
            n = name[0]
            logger.info("    %s: %.4f%%", n, worst_vals[n] * 100)
        logger.info("    Total portfolio impact (equal-weight): %.4f%%", worst_vals.mean() * 100)

    logger.info("\n=== Interpretation ===")
    if mean_corr > 0.7:
        logger.info(
            "HIGH CORRELATION: These 4 positions are effectively one CHF trade. "
            "Allocation limits are not protecting against CHF concentration risk."
        )
    elif mean_corr > 0.5:
        logger.info(
            "MODERATE CORRELATION: Partial concentration risk. A 3+ concurrent loss day occurs ~%.1f%% of the time.",
            pct_three_plus_loss,
        )
    else:
        logger.info(
            "LOW CORRELATION: Positions are reasonably independent. "
            "SELL_ONLY cluster does not create hidden CHF concentration."
        )

    if pct_concurrent_loss > 5:
        logger.warning(
            "CONCENTRATION RISK: ALL-4-negative occurs %.1f%% of trading days. "
            "CHF-weakness periods produce correlated losses across %d positions.",
            pct_concurrent_loss,
            len(CHF_CLUSTER),
        )


if __name__ == "__main__":
    main()
