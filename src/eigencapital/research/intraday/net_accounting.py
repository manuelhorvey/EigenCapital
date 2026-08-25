"""Net-return accounting — per-flip transaction costs inside the series.

Supersedes the Campaign 4–7 backtest cost convention for all future
microstructure evaluation. The legacy engine computed gross Sharpe and
deducted aggregate cost separately; at intraday turnover (hundreds of
thousands of position flips) that materially overstates every "net"
figure — C7's rerun showed net_base == gross == net_adverse for all 18
candidates, which is how the flaw was caught.

Corrected semantics (locked):

    signal → position (sign, shifted one bar: no look-ahead)
           → per-bar gross return = position × forward return
           → cost charged on EVERY position change: |Δposition| × one-way
             cost — including trailing positions whose forward window is
             truncated by the end of the sample (their costs were really
             paid)
           → NET per-bar return → Sharpe / drawdown / economics

Costs are one-way charges applied at each flip, so a round trip pays
2 × one_way — equivalent to the legacy 13/22 bps round-trip convention,
now split across entry and exit.

Usage:
    result = bt_net(bars, signal, hp=1, cost_one_way=6.5e-4)
    assert result.net_sharpe <= result.gross_sharpe + 1e-9
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


@dataclass
class NetResult:
    """Economics of a signal under corrected per-flip accounting.

    Attributes:
        gross_sharpe: Annualized Sharpe of the pre-cost return series
        net_sharpe: Annualized Sharpe AFTER per-flip costs
        total_gross_ret: Sum of gross per-bar returns
        total_net_ret: Sum of net per-bar returns
        total_cost_drag: Total cost paid (= n_flips_weighted × one-way)
        n_flips: Total absolute position changes (weighted by size delta)
        exposure: Fraction of bars with a nonzero position
        max_dd: Maximum drawdown on the NET return series
        worst_bar: Single worst NET bar (tail loss)
        avg_cost_per_flip_bps: One-way cost in basis points (constant)
        bars_per_trading_day: Bar frequency used for annualization
        trading_days_per_year: Year length used for annualization
        hp: Holding horizon in bars used for forward returns
        cost_one_way: One-way cost per unit of position change
    """

    gross_sharpe: float
    net_sharpe: float
    total_gross_ret: float
    total_net_ret: float
    total_cost_drag: float
    n_flips: int
    exposure: float
    max_dd: float
    worst_bar: float
    avg_cost_per_flip_bps: float
    bars_per_trading_day: int = 288
    trading_days_per_year: int = 252
    hp: int = 1
    cost_one_way: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "gross_sharpe": round(self.gross_sharpe, 4),
            "net_sharpe": round(self.net_sharpe, 4),
            "total_gross_ret": round(self.total_gross_ret, 6),
            "total_net_ret": round(self.total_net_ret, 6),
            "total_cost_drag": round(self.total_cost_drag, 6),
            "n_flips": self.n_flips,
            "exposure": round(self.exposure, 4),
            "max_dd": round(self.max_dd, 4),
            "worst_bar": round(self.worst_bar, 8),
            "avg_cost_per_flip_bps": round(self.avg_cost_per_flip_bps, 2),
            "bars_per_trading_day": self.bars_per_trading_day,
            "trading_days_per_year": self.trading_days_per_year,
            "hp": self.hp,
            "cost_one_way": self.cost_one_way,
        }


def bt_net(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int = 1,
    cost_one_way: float = 0.0,
    price_col: str = "close",
    bars_per_trading_day: int = 288,
    trading_days_per_year: int = 252,
) -> NetResult:
    """Backtest a signal with per-flip costs inside the return series.

    Args:
        df: Bar frame containing `price_col` (chronological order required)
        sig: Trading signal aligned to df's index; sign(sig) is the
            target position, entered on the NEXT bar (no look-ahead)
        hp: Forward-return horizon in bars
        cost_one_way: One-way cost per unit of position change
            (e.g. 6.5e-4 = 6.5 bps)
        price_col: Column holding the execution price series
        bars_per_trading_day: Bars per day for annualization
        trading_days_per_year: Trading days per year for annualization

    Returns:
        NetResult with gross and net economics

    Raises:
        ValueError: if `price_col` missing from df or index misaligned
    """
    if price_col not in df.columns:
        raise ValueError(f"df missing price column '{price_col}'")
    if not sig.index.equals(df.index):
        raise ValueError("sig index must equal df index")

    pos = np.sign(sig).shift(1).fillna(0.0)
    fwd = df[price_col].pct_change(hp).shift(-hp)

    gross = pos * fwd
    flips = pos.diff().abs().fillna(0.0)
    # Trailing positions have no forward return window (NaN gross), but
    # their entry/exit costs were really paid — charge them instead of
    # dropping them, so total_net == total_gross − total_cost always.
    net = gross.fillna(0.0) - flips * cost_one_way

    # Series statistics (Sharpe/DD/tail) are evaluated ONLY on bars with
    # a realizable forward return; totals include every paid cost.
    valid = fwd.notna()
    g_eval = gross[valid]
    n_eval = net[valid]
    ann = np.sqrt(trading_days_per_year * bars_per_trading_day / hp)

    def _sharpe(s: pd.Series) -> float:
        if len(s) <= 30 or s.std() == 0:
            return 0.0
        return float(s.mean() / s.std() * ann)

    def _maxdd(s: pd.Series) -> float:
        if s.empty:
            return 0.0
        cum = (1 + s).cumprod()
        return float(((cum - cum.cummax()) / cum.cummax()).min())

    n_flips = int(flips.sum())
    return NetResult(
        gross_sharpe=_sharpe(g_eval),
        net_sharpe=_sharpe(n_eval),
        total_gross_ret=float(g_eval.sum()),
        total_net_ret=float(net.sum()),
        total_cost_drag=float((flips * cost_one_way).sum()),
        n_flips=n_flips,
        exposure=float((pos != 0).mean()),
        max_dd=_maxdd(n_eval),
        worst_bar=float(n_eval.min()) if len(n_eval) else 0.0,
        avg_cost_per_flip_bps=cost_one_way * 10000 if n_flips else 0.0,
        bars_per_trading_day=bars_per_trading_day,
        trading_days_per_year=trading_days_per_year,
        hp=hp,
        cost_one_way=cost_one_way,
    )
