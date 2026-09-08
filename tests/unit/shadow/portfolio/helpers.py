"""Shared synthetic-data helpers for R4-S shadow portfolio tests."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from eigencapital.shadow.portfolio.correlation import CorrelationModel
from eigencapital.shadow.portfolio.exposure import get_factor_group
from eigencapital.shadow.portfolio.selector import ShadowCandidate


def make_returns(
    symbols: List[str],
    n: int = 300,
    seed: int = 1,
    base: float = 0.0003,
    vol: float = 0.01,
    factor_map: Dict[str, float] | None = None,
    common_std: float = 0.02,
) -> pd.DataFrame:
    """Synthetic daily returns. Optional per-symbol shared-factor loading:
    symbols with the same factor value share a common driver → correlated.
    With default vol=0.01 / common_std=0.02, same-factor pairs correlate ≈ 0.8."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    common = rng.normal(0.0, common_std, n) if factor_map else None
    data: Dict[str, np.ndarray] = {}
    for i, sym in enumerate(symbols):
        noise = rng.normal(base, vol, n)
        if factor_map:
            f = factor_map.get(sym, 0.0)
            noise = noise + f * common  # type: ignore[operator]
        data[sym] = noise
    return pd.DataFrame(data, index=idx)


def snapshot_for(returns: pd.DataFrame) -> object:
    """Correlation snapshot at the last available date."""
    return CorrelationModel().build(returns, as_of=returns.index[-1])


def make_candidate(
    sym: str,
    w: float,
    vol: float = 0.15,
    rank: int | None = None,
    feasible: bool = True,
    history_sufficient: bool = True,
) -> ShadowCandidate:
    """Build a ShadowCandidate with production-realistic classification."""
    return ShadowCandidate(
        symbol=sym,
        weight=w,
        direction="LONG" if w > 0 else "SHORT",
        asset_class=_asset_class(sym),
        factor_group=get_factor_group(sym),
        feasible=feasible,
        r4_rank=rank if rank is not None else 1,
        annualized_vol=vol,
        history_sufficient=history_sufficient,
    )


def _asset_class(sym: str) -> str:
    if sym in {"US30", "USTEC", "US500"}:
        return "indices"
    if sym in {"XAUUSD", "XAGUSD"}:
        return "metals"
    if sym in {"BTCUSD", "ETHUSD"}:
        return "crypto"
    if sym == "USOIL":
        return "energy"
    return "forex"


def make_prices(symbols: List[str], base: float = 100.0) -> Dict[str, float]:
    return {s: base for s in symbols}
