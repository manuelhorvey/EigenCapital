"""Cross-asset correlation monitor for portfolio risk.

Tracks rolling pairwise correlations across all traded assets and flags
concentrated cluster risk (correlated positions on the same side).
"""

from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.orchestrator.correlation")


_DEFAULT_POSITION_CONCENTRATION: dict = {
    "long": 0,
    "short": 0,
    "total": 0,
    "skew": 0.0,
    "dominant_side": "none",
    "threshold": 0.75,
    "alert": False,
}


def compute_position_concentration(actors: dict[str, Any]) -> dict:
    """Count open positions per side and compute skew ratio.

    Counts both primary positions (pos_mgr) and re-entry positions.
    Returns a dict with long/short counts, skew, and alert status.
    """
    long_count = 0
    short_count = 0
    for name, actor in actors.items():
        engine = getattr(actor, "_engine", None)
        if engine is None:
            continue
        pos = getattr(engine, "pos_mgr", None)
        if pos is not None and pos.has_position():
            side = getattr(pos.position, "side", None)
            if side == "long":
                long_count += 1
            elif side == "short":
                short_count += 1
        for batch in getattr(engine, "batches", {}).values():
            side = batch.side
            if side == "long":
                long_count += 1
            elif side == "short":
                short_count += 1
    total = long_count + short_count
    if total == 0:
        return dict(_DEFAULT_POSITION_CONCENTRATION)
    long_ratio = long_count / total
    skew = max(long_ratio, 1.0 - long_ratio)
    from paper_trading.config_manager import get_config

    threshold = (get_config().defaults or {}).get("net_short_concentration_threshold", 0.75)
    side_label = "LONG" if long_ratio > 0.5 else "SHORT"
    if skew > threshold:
        logger.warning(
            "POSITION_CONCENTRATION: %d/%d positions on %s side (skew=%.1f%% threshold=%.0f%%)",
            max(long_count, short_count),
            total,
            side_label,
            skew * 100,
            threshold * 100,
        )
        from paper_trading.alerting.manager import global_alert_manager

        with contextlib.suppress(Exception):
            global_alert_manager().warning(
                "Position concentration alert",
                f"{max(long_count, short_count)}/{total} on {side_label} side",
                details={
                    "long": long_count,
                    "short": short_count,
                    "skew": round(skew, 4),
                    "threshold": threshold,
                },
            )
    return {
        "long": long_count,
        "short": short_count,
        "total": total,
        "skew": round(skew, 4),
        "dominant_side": side_label if skew > threshold else "balanced",
        "threshold": threshold,
        "alert": skew > threshold,
    }


class CorrelationMonitor:
    """Monitors cross-asset correlations and cluster concentration.

    Call ``update()`` once per cycle with current prices.  Daily returns
    are accumulated only when a new daily bar is detected (new date).
    """

    def __init__(
        self,
        correlation_threshold: float = 0.7,
        cluster_same_side_threshold: int = 3,
        correlation_window: int = 63,
        min_periods: int = 20,
    ):
        self._correlation_threshold = correlation_threshold
        self._cluster_same_side_threshold = cluster_same_side_threshold
        self._window = correlation_window
        self._min_periods = min_periods
        self._price_data: dict[str, pd.Series] = {}
        self._last_date: str | None = None

    def update(
        self,
        prices: dict[str, float],
        positions: dict[str, dict],
        current_date: str,
    ) -> dict:
        """Process a new cycle's prices and positions.

        Args:
            prices: {asset_name: current_price}
            positions: {asset_name: {"side": "long"/"short"/None}}
            current_date: ISO date string (e.g. "2025-01-15")

        Returns:
            Correlation report dict with keys:
                - high_pairs: list of (asset_a, asset_b, correlation)
                - cluster_alerts: list of alert strings
                - correlation_matrix: {asset: {asset: corr}} or None
        """
        report: dict = {
            "high_pairs": [],
            "cluster_alerts": [],
            "correlation_matrix": None,
        }

        if current_date != self._last_date:
            self._last_date = current_date
            for name, price in prices.items():
                if name not in self._price_data:
                    self._price_data[name] = pd.Series(dtype=float)
                ts = pd.Timestamp(current_date)
                self._price_data[name].loc[ts] = price

        if len(self._price_data) < 2:
            return report

        min_len = min(len(s) for s in self._price_data.values())
        if min_len < self._min_periods:
            return report

        returns = pd.DataFrame({name: s.pct_change().dropna() for name, s in self._price_data.items()})
        returns = returns.iloc[-self._window :]

        corr = returns.corr(min_periods=self._min_periods)
        if corr.empty:
            return report

        report["correlation_matrix"] = {
            str(a): {str(b): float(corr.loc[a, b]) for b in corr.columns} for a in corr.columns
        }

        high_pairs = []
        assets = list(corr.columns)
        for i in range(len(assets)):
            for j in range(i + 1, len(assets)):
                val = corr.loc[assets[i], assets[j]]
                if not np.isnan(val) and abs(val) >= self._correlation_threshold:
                    high_pairs.append((assets[i], assets[j], round(abs(val), 3)))
        report["high_pairs"] = sorted(high_pairs, key=lambda x: -x[2])

        cluster_alerts = self._check_clusters(corr, positions)
        report["cluster_alerts"] = cluster_alerts

        return report

    def compute_portfolio_correlation(self, actors: dict[str, Any]) -> dict:
        """Build price/position snapshots from actors and compute correlation.

        One-shot convenience wrapper around update() that extracts prices
        and positions from the actor dict. Returns the correlation report
        dict with keys: n_high_pairs, cluster_alerts.
        """
        prices: dict[str, float] = {}
        positions: dict[str, dict] = {}
        from eigencapital.domain.time import utc_now

        for name, actor in actors.items():
            engine = getattr(actor, "_engine", None)
            if engine is None:
                continue
            px = getattr(engine, "current_price", None)
            if px is not None and px > 0:
                prices[name] = px
            pos = getattr(engine, "pos_mgr", None)
            if pos is not None and pos.has_position():
                side = pos.position.side if hasattr(pos.position, "side") else None
                positions[name] = {"side": side.value if hasattr(side, "value") else side}
        today_str = utc_now().strftime("%Y-%m-%d")
        corr_report = self.update(prices, positions, today_str)
        if any("cluster" in a for a in corr_report["cluster_alerts"]):
            logger.warning("Correlation cluster alert: %s", corr_report["cluster_alerts"])
        return {"n_high_pairs": len(corr_report["high_pairs"]), "cluster_alerts": corr_report["cluster_alerts"]}

    def _check_clusters(self, corr: pd.DataFrame, positions: dict[str, dict]) -> list[str]:
        """Detect clusters of highly-correlated assets on the same side."""
        alerts: list[str] = []
        assets = list(corr.columns)
        visited: set[str] = set()

        for asset in assets:
            if asset in visited:
                continue
            cluster = {asset}
            for other in assets:
                if other == asset or other in visited:
                    continue
                val = corr.loc[asset, other]
                if not np.isnan(val) and abs(val) >= self._correlation_threshold:
                    cluster.add(other)

            if len(cluster) >= self._cluster_same_side_threshold:
                sides = [(a, positions.get(a, {}).get("side")) for a in cluster]
                side_counts: dict[str | None, int] = defaultdict(int)
                for _, s in sides:
                    side_counts[s] += 1
                dominant_side = max(side_counts, key=lambda k: side_counts[k])
                count = side_counts[dominant_side]
                if count >= self._cluster_same_side_threshold and dominant_side is not None:
                    alerts.append(
                        f"cluster_{len(cluster)}_assets_corr>{self._correlation_threshold}: "
                        f"{count}_{dominant_side} — {', '.join(a for a, s in sides if s == dominant_side)}"
                    )

            visited.update(cluster)

        return alerts
