"""Directional win rate tracker — tracks BUY and SELL win rates separately per asset.

Provides breakeven WR computation and win-rate-gap analysis for TP/SL optimization.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("quorrin.optimization.directional_win_rate")


@dataclass
class _DirectionalDeque:
    """Rolling window of trade outcomes for a single direction (BUY or SELL)."""

    window: int = 20
    _outcomes: deque[bool] = field(default_factory=lambda: deque(maxlen=20))

    def record(self, is_win: bool) -> None:
        self._outcomes.append(is_win)

    @property
    def win_rate(self) -> float:
        if not self._outcomes:
            return 0.0
        return sum(self._outcomes) / len(self._outcomes)

    @property
    def n_trades(self) -> int:
        return len(self._outcomes)

    def reset(self) -> None:
        self._outcomes.clear()


class DirectionalWinRateTracker:
    """Tracks BUY and SELL win rates separately per asset.

    Usage:
        tracker = DirectionalWinRateTracker(window=20)
        tracker.record("EURUSD", "long", tp_hit=True)
        tracker.record("EURUSD", "short", tp_hit=False)
        stats = tracker.get("EURUSD")
    """

    def __init__(self, window: int = 20):
        self._window = window
        self._data: dict[str, dict[str, _DirectionalDeque]] = {}

    def record(self, asset: str, side: str, is_win: bool) -> None:
        """Record a trade outcome for a given asset and direction.

        Parameters
        ----------
        asset : str
            Asset name (e.g. \"EURUSD\").
        side : str
            \"long\" (BUY) or \"short\" (SELL).
        is_win : bool
            True if the trade was a win (TP hit), False if loss (SL hit).
        """
        side_key = side.lower()
        if side_key not in ("long", "short"):
            logger.warning("Invalid side: %s — must be 'long' or 'short'", side)
            return
        if asset not in self._data:
            self._data[asset] = {
                "long": _DirectionalDeque(window=self._window),
                "short": _DirectionalDeque(window=self._window),
            }
        self._data[asset][side_key].record(is_win)

    def get(self, asset: str) -> dict[str, Any]:
        """Return directional win rates and derived metrics for an asset.

        Parameters
        ----------
        asset : str
            Asset name.

        Returns
        -------
        dict with keys:
            buy_wr, sell_wr, buy_n, sell_n, combined_wr, combined_n
        """
        if asset not in self._data:
            return {
                "buy_wr": 0.0,
                "sell_wr": 0.0,
                "buy_n": 0,
                "sell_n": 0,
                "combined_wr": 0.0,
                "combined_n": 0,
            }
        buy = self._data[asset]["long"]
        sell = self._data[asset]["short"]
        buy_wr = buy.win_rate
        sell_wr = sell.win_rate
        buy_n = buy.n_trades
        sell_n = sell.n_trades
        combined_n = buy_n + sell_n
        combined_wr = 0.0
        if combined_n > 0:
            buy_wins = round(buy_wr * buy_n)
            sell_wins = round(sell_wr * sell_n)
            combined_wr = (buy_wins + sell_wins) / combined_n
        return {
            "buy_wr": buy_wr,
            "sell_wr": sell_wr,
            "buy_n": buy_n,
            "sell_n": sell_n,
            "combined_wr": combined_wr,
            "combined_n": combined_n,
        }

    def breakeven_wr(self, tp_mult: float, sl_mult: float) -> float:
        """Breakeven win rate for a given (tp_mult, sl_mult) pair.

        Formula: sl / (tp + sl)
        """
        return sl_mult / (tp_mult + sl_mult) if (tp_mult + sl_mult) > 0 else 1.0

    def win_rate_gap(self, asset: str, tp_mult: float, sl_mult: float) -> dict[str, float]:
        """Return how far each direction's WR is above/below breakeven.

        Positive gap = direction is profitable.
        Negative gap = direction is losing money.

        Parameters
        ----------
        asset : str
            Asset name.
        tp_mult : float
            Take-profit multiplier.
        sl_mult : float
            Stop-loss multiplier.

        Returns
        -------
        dict with keys: buy_gap, sell_gap, combined_gap, directional_asymmetry
        """
        be = self.breakeven_wr(tp_mult, sl_mult)
        stats = self.get(asset)
        buy_gap = stats["buy_wr"] - be if stats["buy_n"] > 0 else 0.0
        sell_gap = stats["sell_wr"] - be if stats["sell_n"] > 0 else 0.0
        combined_gap = stats["combined_wr"] - be if stats["combined_n"] > 0 else 0.0
        directional_asymmetry = abs(buy_gap - sell_gap)
        return {
            "buy_gap": round(buy_gap, 4),
            "sell_gap": round(sell_gap, 4),
            "combined_gap": round(combined_gap, 4),
            "directional_asymmetry": round(directional_asymmetry, 4),
        }

    def all_assets(self) -> list[str]:
        return list(self._data.keys())

    def reset(self, asset: str | None = None) -> None:
        if asset:
            if asset in self._data:
                self._data[asset]["long"].reset()
                self._data[asset]["short"].reset()
        else:
            self._data.clear()
