"""Campaign 3 — M1/Tick-Level Intraday Research.

Unlike Campaigns 1-2 (M5 price/microstructure → 44/44 rejected),
Campaign 3 investigates information sources that M5 CANNOT preserve:

1. Order-flow proxies (tick direction, volume imbalance, aggressor modeling)
2. Liquidity dynamics (spread shocks, volume bursts, depth changes)
3. Session microstructure (open/close effects, overlap transitions, overnight gaps)

Every hypothesis is pre-registered and frozen before evaluation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List

import numpy as np
import pandas as pd


class HypothesisVerdict(str, Enum):
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    FRAGILE = "fragile"
    COST_SENSITIVE = "cost_sensitive"
    REGIME_DEPENDENT = "regime_dependent"
    CAPACITY_LIMITED = "capacity_limited"
    REDUNDANT = "redundant"
    SUPPORTED = "supported"
    INCREMENTAL = "incremental"
    PRODUCTION_CANDIDATE = "production_candidate"


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    family: str
    description: str
    signal_func: str  # name of signal generator function
    holding_periods: List[int]  # in M1 bars
    economic_rationale: str
    pre_registered_hash: str = ""


def _compute_hyp_hash(h: Hypothesis) -> str:
    data = {
        "id": h.hypothesis_id,
        "family": h.family,
        "signal": h.signal_func,
        "holding": h.holding_periods,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


# ── Signal generators ──────────────────────────────────────────────────


def signal_tick_direction(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Order-flow proxy: net tick direction over lookback."""
    direction = np.sign(df["close"].diff())
    return direction.rolling(lookback).sum() / lookback


def signal_volume_imbalance(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
    """Order-flow proxy: volume-weighted up vs down."""
    direction = np.sign(df["close"].diff())
    vol_weighted = direction * df["tick_volume"]
    up_vol = vol_weighted.clip(lower=0).rolling(lookback).sum()
    dn_vol = (-vol_weighted.clip(upper=0)).rolling(lookback).sum()
    total = up_vol + dn_vol
    return (up_vol - dn_vol) / total.replace(0, np.nan)


def signal_vwap_deviation(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Price distance from rolling VWAP."""
    cum_vol = df["tick_volume"].rolling(lookback).sum()
    cum_pv = (df["close"] * df["tick_volume"]).rolling(lookback).sum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return (df["close"] - vwap) / vwap.replace(0, np.nan)


def signal_spread_shock(
    df: pd.DataFrame, lookback: int = 60, shock_pct: float = 1.5
) -> pd.Series:
    """Liquidity proxy: spread relative to its rolling median."""
    med = df["spread"].rolling(lookback).median()
    return df["spread"] / med.replace(0, np.nan)


def signal_volume_burst(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Liquidity proxy: current volume / rolling average."""
    avg = df["tick_volume"].rolling(lookback).mean()
    return df["tick_volume"] / avg.replace(0, np.nan)


def signal_range_position(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
    """Where is price within its recent range? [0, 1]"""
    high = df["high"].rolling(lookback).max()
    low = df["low"].rolling(lookback).min()
    rng = high - low
    return (df["close"] - low) / rng.replace(0, np.nan)


def signal_intraday_momentum(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Short-horizon M1 momentum — different from M5 because M1 captures micro-momentum."""
    return df["close"].pct_change(lookback)


def signal_reversal_extreme(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
    """Extreme displacement from rolling mean — mean reversion candidate."""
    mean = df["close"].rolling(lookback).mean()
    std = df["close"].rolling(lookback).std()
    return -(df["close"] - mean) / std.replace(0, np.nan)


def signal_aggressor_proxy(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Aggressor direction proxy: close vs mid-price trend."""
    mid = (df["high"] + df["low"]) / 2
    close_vs_mid = np.sign(df["close"] - mid)
    return close_vs_mid.rolling(lookback).sum() / lookback


def signal_volatility_regime(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Realized vol regime: current vs rolling average."""
    ret = df["close"].pct_change()
    rv = ret.rolling(lookback).std()
    rv_avg = rv.rolling(lookback * 4).mean()
    return rv / rv_avg.replace(0, np.nan)


def signal_session_open_momentum(
    df: pd.DataFrame, session_start_idx: int = 0, lookback: int = 30
) -> pd.Series:
    """Momentum in first N bars of session."""
    ret = df["close"].pct_change(1)
    return ret.rolling(lookback).sum()


def signal_price_acceleration(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Second derivative of price — acceleration/deceleration."""
    ret1 = df["close"].pct_change(1)
    ret2 = ret1.diff(lookback)
    return ret2


def signal_overnight_gap_proxy(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Gap-like behavior at session boundaries: price jump vs rolling close."""
    prev_close = df["close"].shift(1)
    gap = (df["open"] - prev_close) / prev_close.replace(0, np.nan)
    return gap.rolling(lookback).mean()


# ── Signal registry ────────────────────────────────────────────────────

SIGNAL_REGISTRY: Dict[str, Callable] = {
    "tick_direction": signal_tick_direction,
    "volume_imbalance": signal_volume_imbalance,
    "vwap_deviation": signal_vwap_deviation,
    "spread_shock": signal_spread_shock,
    "volume_burst": signal_volume_burst,
    "range_position": signal_range_position,
    "intraday_momentum": signal_intraday_momentum,
    "reversal_extreme": signal_reversal_extreme,
    "aggressor_proxy": signal_aggressor_proxy,
    "volatility_regime": signal_volatility_regime,
    "session_open_momentum": signal_session_open_momentum,
    "price_acceleration": signal_price_acceleration,
    "overnight_gap_proxy": signal_overnight_gap_proxy,
}


# ── Hypothesis library ─────────────────────────────────────────────────

CAMPAIGN3_HYPOTHESES: List[Hypothesis] = [
    # Family: Order-Flow Proxies (Tier 1)
    Hypothesis(
        hypothesis_id="OF-001",
        family="order_flow",
        description="Tick direction persistence: net up/down ticks predict next-bar direction",
        signal_func="tick_direction",
        holding_periods=[5, 15, 30],
        economic_rationale="Short-term order flow imbalance creates temporary price pressure",
    ),
    Hypothesis(
        hypothesis_id="OF-002",
        family="order_flow",
        description="Volume-weighted direction: volume-weighted up vs down flow predicts continuation",
        signal_func="volume_imbalance",
        holding_periods=[5, 15, 30],
        economic_rationale="Large volume in one direction suggests informed trading",
    ),
    Hypothesis(
        hypothesis_id="OF-003",
        family="order_flow",
        description="VWAP deviation: distance from rolling VWAP predicts reversion or continuation",
        signal_func="vwap_deviation",
        holding_periods=[15, 30, 60],
        economic_rationale="Institutional orders cluster around VWAP; deviation signals temporary dislocation",
    ),
    Hypothesis(
        hypothesis_id="OF-004",
        family="order_flow",
        description="Aggressor proxy: close vs mid-price direction predicts next-bar movement",
        signal_func="aggressor_proxy",
        holding_periods=[5, 15, 30],
        economic_rationale="Aggressive buying/selling leaves directional footprint in bar close position",
    ),
    # Family: Liquidity Dynamics (Tier 2)
    Hypothesis(
        hypothesis_id="LQ-001",
        family="liquidity",
        description="Spread shock: spread widening predicts volatility expansion or reversal",
        signal_func="spread_shock",
        holding_periods=[5, 15, 30],
        economic_rationale="Spread widening signals reduced liquidity; price may overshoot then revert",
    ),
    Hypothesis(
        hypothesis_id="LQ-002",
        family="liquidity",
        description="Volume burst: sudden volume increase predicts directional move or exhaustion",
        signal_func="volume_burst",
        holding_periods=[5, 15, 30],
        economic_rationale="Volume bursts indicate institutional activity or news events",
    ),
    Hypothesis(
        hypothesis_id="LQ-003",
        family="liquidity",
        description="Combined liquidity signal: spread shock + volume burst interaction",
        signal_func="spread_shock",  # will be combined in evaluation
        holding_periods=[10, 20],
        economic_rationale="Simultaneous spread widening and volume burst is strongest liquidity signal",
    ),
    # Family: Price Structure at M1 (Tier 3)
    Hypothesis(
        hypothesis_id="PS-001",
        family="price_structure",
        description="Range position: where price sits within recent range predicts breakout or reversion",
        signal_func="range_position",
        holding_periods=[10, 30, 60],
        economic_rationale="Extreme range positions may signal exhaustion or breakout",
    ),
    Hypothesis(
        hypothesis_id="PS-002",
        family="price_structure",
        description="Intraday momentum: short-horizon M1 momentum — micro-momentum different from M5",
        signal_func="intraday_momentum",
        holding_periods=[5, 15, 30],
        economic_rationale="M1 momentum captures microstructure persistence invisible at M5",
    ),
    Hypothesis(
        hypothesis_id="PS-003",
        family="price_structure",
        description="Reversal extreme: standardized displacement from mean predicts reversion",
        signal_func="reversal_extreme",
        holding_periods=[10, 30, 60],
        economic_rationale="Extreme z-score displacements revert at M1 when driven by noise, not information",
    ),
    Hypothesis(
        hypothesis_id="PS-004",
        family="price_structure",
        description="Price acceleration: second derivative of price predicts continuation or exhaustion",
        signal_func="price_acceleration",
        holding_periods=[5, 15, 30],
        economic_rationale="Accelerating price moves tend to continue; decelerating moves tend to reverse",
    ),
    # Family: Volatility/Regime (Tier 4)
    Hypothesis(
        hypothesis_id="VR-001",
        family="volatility_regime",
        description="Realized vol regime: current vol vs average predicts expansion or contraction",
        signal_func="volatility_regime",
        holding_periods=[15, 30, 60],
        economic_rationale="Volatility mean-reverts; high vol periods precede directional moves",
    ),
    # Family: Session Microstructure (Tier 5)
    Hypothesis(
        hypothesis_id="SS-001",
        family="session_structure",
        description="Session open momentum: first-bar direction predicts session continuation",
        signal_func="session_open_momentum",
        holding_periods=[15, 30, 60],
        economic_rationale="Session open often reflects overnight accumulation; direction may persist",
    ),
    Hypothesis(
        hypothesis_id="SS-002",
        family="session_structure",
        description="Overnight gap behavior: gap size/direction predicts intraday fill or continuation",
        signal_func="overnight_gap_proxy",
        holding_periods=[30, 60, 120],
        economic_rationale="Gaps from overnight sessions may fill or extend depending on information content",
    ),
    # Family: Composite (Tier 6)
    Hypothesis(
        hypothesis_id="CP-001",
        family="composite",
        description="Order-flow + liquidity composite: tick direction conditioned on volume burst",
        signal_func="tick_direction",  # combined in evaluation
        holding_periods=[10, 20],
        economic_rationale="Order flow is more informative during high-activity periods",
    ),
    Hypothesis(
        hypothesis_id="CP-002",
        family="composite",
        description="Momentum + volatility regime: momentum signal conditioned on vol state",
        signal_func="intraday_momentum",
        holding_periods=[15, 30],
        economic_rationale="Momentum works better in trending vol regimes, poorly in choppy ones",
    ),
]

# Pre-compute hashes
for hyp in CAMPAIGN3_HYPOTHESES:
    object.__setattr__(hyp, "pre_registered_hash", _compute_hyp_hash(hyp))
