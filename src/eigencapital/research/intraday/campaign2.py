"""Campaign 2 — Microstructure / Volume-Based Intraday Research.

Campaign 1 found 0/24 survivors with simple price-based M5 signals.
Campaign 2 changes the INFORMATION SOURCE: volume, spread, range patterns,
session microstructure, and liquidity proxies.

Frozen Campaign 1 results: ALL REJECTED (simple price-based M5 alpha absent).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd

from .hypotheses import HypothesisDefinition, HypothesisFamily, HoldingPeriod, Verdict

logger = logging.getLogger(__name__)


# ============================================================
# Campaign 2 Hypothesis Library
# ============================================================

@dataclass(frozen=True)
class MicroHypothesis:
    """Pre-registered microstructure hypothesis."""
    hypothesis_id: str
    name: str
    description: str
    economic_rationale: str
    signal_source: str  # "volume", "spread", "range", "session", "composite"
    holding_period: str
    falsification_criteria: Dict[str, Any]
    cost_sensitivity: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "name": self.name,
            "description": self.description,
            "economic_rationale": self.economic_rationale,
            "signal_source": self.signal_source,
            "holding_period": self.holding_period,
            "falsification_criteria": self.falsification_criteria,
            "cost_sensitivity": self.cost_sensitivity,
        }


# TIER 1: Volume-Based
MICRO_HYP_001 = MicroHypothesis(
    hypothesis_id="MIC-VOL-001",
    name="Volume Spike Momentum",
    description="Bars with volume > 2x average predict continuation of bar direction",
    economic_rationale="High volume indicates institutional activity; directional conviction persists",
    signal_source="volume",
    holding_period="15min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_002 = MicroHypothesis(
    hypothesis_id="MIC-VOL-002",
    name="Volume Dry-Up Reversal",
    description="Low volume (<0.5x average) during a trend predicts exhaustion and reversal",
    economic_rationale="Declining participation signals fading conviction",
    signal_source="volume",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="high",
)

MICRO_HYP_003 = MicroHypothesis(
    hypothesis_id="MIC-VOL-003",
    name="Volume-Price Divergence",
    description="Price makes new high but volume declines — bearish divergence predicts reversal",
    economic_rationale="Divergence between price and participation signals distribution",
    signal_source="volume",
    holding_period="1hour",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_004 = MicroHypothesis(
    hypothesis_id="MIC-VOL-004",
    name="Volume-Weighted Momentum",
    description="Weight momentum signal by volume — high-volume momentum is stronger",
    economic_rationale="Volume confirms directional conviction; volume-weighted moves persist",
    signal_source="volume",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

# TIER 2: Spread-Based
MICRO_HYP_005 = MicroHypothesis(
    hypothesis_id="MIC-SPR-001",
    name="Spread Expansion Contrarian",
    description="Wide spreads indicate stress; contrarian trades capture mean reversion",
    economic_rationale="Wide spreads signal informed trading or distress; mean reversion follows",
    signal_source="spread",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="high",
)

MICRO_HYP_006 = MicroHypothesis(
    hypothesis_id="MIC-SPR-002",
    name="Spread Tightening Continuation",
    description="Narrow spreads after expansion signal calm continuation of trend",
    economic_rationale="Tight spreads indicate consensus; trends persist in consensus regimes",
    signal_source="spread",
    holding_period="1hour",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

MICRO_HYP_007 = MicroHypothesis(
    hypothesis_id="MIC-SPR-003",
    name="Spread-Volume Interaction",
    description="Wide spread + high volume = informed trading; follow the direction",
    economic_rationale="Informed traders widen spreads; their direction tends to persist",
    signal_source="spread",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

# TIER 3: Range/Structure-Based
MICRO_HYP_008 = MicroHypothesis(
    hypothesis_id="MIC-RNG-001",
    name="Range Expansion Momentum",
    description="Expanding bar ranges predict continuation of the range expansion direction",
    economic_rationale="Range expansion indicates information arrival; trend persists",
    signal_source="range",
    holding_period="15min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_009 = MicroHypothesis(
    hypothesis_id="MIC-RNG-002",
    name="Range Compression Breakout",
    description="Narrow ranges (<0.5x average) followed by expansion predict directional breakout",
    economic_rationale="Compression stores energy; expansion releases it directionally",
    signal_source="range",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_010 = MicroHypothesis(
    hypothesis_id="MIC-RNG-003",
    name="Bar Body Ratio Momentum",
    description="Bars with large body relative to range indicate strong directional conviction",
    economic_rationale="Full-body bars show one-sided pressure; continuation follows",
    signal_source="range",
    holding_period="15min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_011 = MicroHypothesis(
    hypothesis_id="MIC-RNG-004",
    name="Upper/Lower Shadow Rejection",
    description="Long upper shadow at high = rejection; short at resistance; vice versa",
    economic_rationale="Wicks show failed attempts; rejection levels attract further selling/buying",
    signal_source="range",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="high",
)

# TIER 4: Session Microstructure
MICRO_HYP_012 = MicroHypothesis(
    hypothesis_id="MIC-SES-001",
    name="London Open Volume Surge",
    description="Volume spike at London open predicts directional continuation",
    economic_rationale="Institutional orders cluster at session open; volume confirms direction",
    signal_source="session",
    holding_period="1hour",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

MICRO_HYP_013 = MicroHypothesis(
    hypothesis_id="MIC-SES-002",
    name="NY Open Volume Surge",
    description="Volume spike at NY open predicts directional continuation",
    economic_rationale="US institutional flow at open creates persistent directional pressure",
    signal_source="session",
    holding_period="1hour",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

MICRO_HYP_014 = MicroHypothesis(
    hypothesis_id="MIC-SES-003",
    name="Session Transition Volatility",
    description="Volatility at session transitions (Asian→London, London→NY) predicts breakout",
    economic_rationale="Information from previous session is incorporated at transitions",
    signal_source="session",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_015 = MicroHypothesis(
    hypothesis_id="MIC-SES-004",
    name="End-of-Session Exhaustion",
    description="Late-session volume decline + small bars predict next-session reversal",
    economic_rationale="Exhaustion at session end; fresh orders at next session open reverse",
    signal_source="session",
    holding_period="session_close",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

# TIER 5: Composite Microstructure
MICRO_HYP_016 = MicroHypothesis(
    hypothesis_id="MIC-CMP-001",
    name="Volume-Range Momentum",
    description="High volume + expanding range in same direction = strong continuation signal",
    economic_rationale="Volume confirms range expansion; dual confirmation increases persistence",
    signal_source="composite",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_017 = MicroHypothesis(
    hypothesis_id="MIC-CMP-002",
    name="Volume-Range Divergence",
    description="Range expands but volume declines — divergence predicts reversal",
    economic_rationale="Unconfirmed moves lack institutional support; reversal follows",
    signal_source="composite",
    holding_period="1hour",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_018 = MicroHypothesis(
    hypothesis_id="MIC-CMP-003",
    name="Spread-Volume-Range Composite",
    description="Wide spread + high volume + large range = informed directional conviction",
    economic_rationale="Triple confirmation of informed activity; strongest persistence",
    signal_source="composite",
    holding_period="30min",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_019 = MicroHypothesis(
    hypothesis_id="MIC-CMP-004",
    name="Liquidity Withdrawal Signal",
    description="Narrowing spread + declining volume = liquidity withdrawal; anticipate volatility",
    economic_rationale="Market makers pulling back; volatility expansion follows",
    signal_source="composite",
    holding_period="15min",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

MICRO_HYP_020 = MicroHypothesis(
    hypothesis_id="MIC-CMP-005",
    name="Volume-Session Momentum",
    description="Above-average volume during trending session predicts continuation into next session",
    economic_rationale="Persistent institutional flow across sessions; session-overlap momentum",
    signal_source="composite",
    holding_period="2hour",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

ALL_MICRO_HYPOTHESES = [
    MICRO_HYP_001, MICRO_HYP_002, MICRO_HYP_003, MICRO_HYP_004,
    MICRO_HYP_005, MICRO_HYP_006, MICRO_HYP_007,
    MICRO_HYP_008, MICRO_HYP_009, MICRO_HYP_010, MICRO_HYP_011,
    MICRO_HYP_012, MICRO_HYP_013, MICRO_HYP_014, MICRO_HYP_015,
    MICRO_HYP_016, MICRO_HYP_017, MICRO_HYP_018, MICRO_HYP_019, MICRO_HYP_020,
]


def compute_micro_library_hash() -> str:
    data = json.dumps([h.to_dict() for h in ALL_MICRO_HYPOTHESES], sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


# ============================================================
# Microstructure Signal Generators
# ============================================================

def _vol_avg(df: pd.DataFrame, window: int = 36) -> pd.Series:
    """Average volume over window."""
    return df["volume"].rolling(window).mean()


def _spread_avg(df: pd.DataFrame, window: int = 36) -> pd.Series:
    """Average spread over window."""
    return df["spread"].rolling(window).mean()


def _range_avg(df: pd.DataFrame, window: int = 36) -> pd.Series:
    """Average bar range over window."""
    return (df["high"] - df["low"]).rolling(window).mean()


def generate_micro_signal(df: pd.DataFrame, hyp: MicroHypothesis) -> pd.Series:
    """Generate signal for a microstructure hypothesis."""
    fid = hyp.hypothesis_id

    vol = df["volume"]
    spr = df["spread"]
    bar_range = df["high"] - df["low"]
    body = df["close"] - df["open"]
    body_abs = body.abs()
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]
    direction = np.sign(body)

    vol_avg = _vol_avg(df)
    spr_avg = _spread_avg(df)
    range_avg = _range_avg(df)

    signal = pd.Series(0, index=df.index)

    if fid == "MIC-VOL-001":
        # Volume spike momentum
        vol_spike = vol > vol_avg * 2
        signal[vol_spike & (direction > 0)] = 1
        signal[vol_spike & (direction < 0)] = -1

    elif fid == "MIC-VOL-002":
        # Volume dry-up reversal
        vol_dry = vol < vol_avg * 0.5
        # Check if in a trend (recent returns)
        recent = df["close"].pct_change().rolling(12).sum()
        signal[vol_dry & (recent > 0)] = -1  # reverse uptrend
        signal[vol_dry & (recent < 0)] = 1   # reverse downtrend

    elif fid == "MIC-VOL-003":
        # Volume-price divergence
        price_high = df["close"] == df["close"].rolling(36).max()
        vol_declining = vol < vol_avg * 0.8
        signal[price_high & vol_declining] = -1  # bearish divergence
        price_low = df["close"] == df["close"].rolling(36).min()
        signal[price_low & vol_declining] = 1   # bullish divergence

    elif fid == "MIC-VOL-004":
        # Volume-weighted momentum
        vol_weight = vol / vol_avg.replace(0, np.nan)
        vw_return = df["close"].pct_change() * vol_weight
        vw_cum = vw_return.rolling(12).sum()
        vol_threshold = vw_cum.rolling(36).std() * 0.5
        signal[vw_cum > vol_threshold] = 1
        signal[vw_cum < -vol_threshold] = -1

    elif fid == "MIC-SPR-001":
        # Spread expansion contrarian
        spread_wide = spr > spr_avg * 2
        recent = df["close"].pct_change().rolling(6).sum()
        signal[spread_wide & (recent > 0)] = -1  # contrarian short
        signal[spread_wide & (recent < 0)] = 1   # contrarian long

    elif fid == "MIC-SPR-002":
        # Spread tightening continuation
        spread_narrow = spr < spr_avg * 0.7
        recent = df["close"].pct_change().rolling(12).sum()
        signal[spread_narrow & (recent > 0)] = 1
        signal[spread_narrow & (recent < 0)] = -1

    elif fid == "MIC-SPR-003":
        # Spread-volume interaction
        spread_wide = spr > spr_avg * 1.5
        vol_high = vol > vol_avg * 1.5
        informed = spread_wide & vol_high
        signal[informed & (direction > 0)] = 1
        signal[informed & (direction < 0)] = -1

    elif fid == "MIC-RNG-001":
        # Range expansion momentum
        range_expand = bar_range > range_avg * 1.5
        signal[range_expand & (direction > 0)] = 1
        signal[range_expand & (direction < 0)] = -1

    elif fid == "MIC-RNG-002":
        # Range compression breakout
        range_narrow = bar_range < range_avg * 0.5
        range_expand = bar_range > range_avg * 1.5
        compression = range_narrow.rolling(12).sum() > 6
        signal[compression & range_expand & (direction > 0)] = 1
        signal[compression & range_expand & (direction < 0)] = -1

    elif fid == "MIC-RNG-003":
        # Bar body ratio momentum
        body_ratio = body_abs / bar_range.replace(0, np.nan)
        strong_body = body_ratio > 0.7
        signal[strong_body & (direction > 0)] = 1
        signal[strong_body & (direction < 0)] = -1

    elif fid == "MIC-RNG-004":
        # Shadow rejection
        upper_reject = upper_shadow > body_abs * 2
        lower_reject = lower_shadow > body_abs * 2
        signal[upper_reject] = -1  # rejected at high → short
        signal[lower_reject] = 1   # rejected at low → long

    elif fid == "MIC-SES-001":
        # London open volume surge
        if "is_london_open" in df.columns:
            vol_surge = vol > vol_avg * 2
            in_open = df["is_london_open"].astype(bool)
            signal[in_open & vol_surge & (direction > 0)] = 1
            signal[in_open & vol_surge & (direction < 0)] = -1

    elif fid == "MIC-SES-002":
        # NY open volume surge
        if "is_new_york" in df.columns:
            vol_surge = vol > vol_avg * 2
            # First 30 min of NY
            ny_bars = df.groupby(
                (df["session_name"] != df["session_name"].shift()).cumsum()
            ).cumcount()
            in_ny_early = df["is_new_york"].astype(bool) & (ny_bars < 6)
            signal[in_ny_early & vol_surge & (direction > 0)] = 1
            signal[in_ny_early & vol_surge & (direction < 0)] = -1

    elif fid == "MIC-SES-003":
        # Session transition volatility
        if "is_london" in df.columns or "is_new_york" in df.columns:
            # First 6 bars of each major session
            session_groups = (df["session_name"] != df["session_name"].shift()).cumsum()
            bars_in = df.groupby(session_groups).cumcount()
            vol_surge = vol > vol_avg * 1.5
            early_session = bars_in < 6
            signal[early_session & vol_surge & (direction > 0)] = 1
            signal[early_session & vol_surge & (direction < 0)] = -1

    elif fid == "MIC-SES-004":
        # End-of-session exhaustion
        if "session_name" in df.columns:
            session_groups = (df["session_name"] != df["session_name"].shift()).cumsum()
            bars_in = df.groupby(session_groups).cumcount()
            session_len = df.groupby(session_groups)["time"].transform("count")
            late_session = bars_in > session_len * 0.8
            vol_declining = vol < vol_avg * 0.6
            small_bars = bar_range < range_avg * 0.6
            exhaustion = late_session & vol_declining & small_bars
            recent = df["close"].pct_change().rolling(12).sum()
            signal[exhaustion & (recent > 0)] = -1
            signal[exhaustion & (recent < 0)] = 1

    elif fid == "MIC-CMP-001":
        # Volume-range momentum
        vol_high = vol > vol_avg * 1.5
        range_expand = bar_range > range_avg * 1.3
        dual = vol_high & range_expand
        signal[dual & (direction > 0)] = 1
        signal[dual & (direction < 0)] = -1

    elif fid == "MIC-CMP-002":
        # Volume-range divergence
        range_expand = bar_range > range_avg * 1.5
        vol_declining = vol < vol_avg * 0.7
        divergence = range_expand & vol_declining
        signal[divergence & (direction > 0)] = -1
        signal[divergence & (direction < 0)] = 1

    elif fid == "MIC-CMP-003":
        # Spread-volume-range composite
        spread_wide = spr > spr_avg * 1.5
        vol_high = vol > vol_avg * 1.5
        range_large = bar_range > range_avg * 1.5
        triple = spread_wide & vol_high & range_large
        signal[triple & (direction > 0)] = 1
        signal[triple & (direction < 0)] = -1

    elif fid == "MIC-CMP-004":
        # Liquidity withdrawal
        spread_narrow = spr < spr_avg * 0.7
        vol_low = vol < vol_avg * 0.5
        withdrawal = spread_narrow & vol_low
        # Predicts upcoming volatility — use as filter, not directional
        # Direction from recent trend
        recent = df["close"].pct_change().rolling(6).sum()
        signal[withdrawal & (recent > 0)] = 1   # continue trend
        signal[withdrawal & (recent < 0)] = -1

    elif fid == "MIC-CMP-005":
        # Volume-session momentum
        if "session_name" in df.columns:
            vol_above = vol > vol_avg * 1.2
            recent = df["close"].pct_change().rolling(24).sum()
            vol_momentum = vol_above & (recent.abs() > recent.rolling(36).std())
            signal[vol_momentum & (recent > 0)] = 1
            signal[vol_momentum & (recent < 0)] = -1

    return signal


# ============================================================
# Campaign 2 Evaluator
# ============================================================

def _safe_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 10 or r.std() == 0:
        return 0.0
    return float((r.mean() / r.std()) * np.sqrt(288 * 252))


def evaluate_micro_strategy(
    df: pd.DataFrame,
    signal: pd.Series,
    cost_per_trade_bps: float = 11.0,
) -> Dict[str, Any]:
    """Evaluate microstructure signal with realistic costs."""
    if signal.abs().sum() == 0:
        return {"gross_sharpe": 0, "net_sharpe": 0, "max_dd": 0, "trades": 0,
                "turnover": 0, "hit_rate": 0, "cost_pct": 100}

    fwd = df["close"].pct_change().shift(-1)
    position = signal.shift(1).fillna(0)

    gross_ret = position * fwd
    trades = int((position.diff().abs() > 0).sum())
    bars = len(position)
    years = bars / (288 * 252)
    turnover = trades / max(years, 0.01)

    cost_per = cost_per_trade_bps / 10000
    net_ret = gross_ret - (position.diff().abs().fillna(0) * cost_per)

    gross_sharpe = _safe_sharpe(gross_ret)
    net_sharpe = _safe_sharpe(net_ret)

    cum = (1 + gross_ret).cumprod()
    dd = cum / cum.cummax() - 1
    max_dd = float(dd.min() * 100) if len(dd) > 0 else 0

    valid = gross_ret.dropna()
    hit_rate = float((valid > 0).sum() / max(len(valid), 1))

    gross_pnl = gross_ret.sum()
    cost_total = trades * cost_per
    cost_pct = float(cost_total / abs(gross_pnl) * 100) if gross_pnl != 0 else 100

    return {
        "gross_sharpe": gross_sharpe,
        "net_sharpe": net_sharpe,
        "max_dd": max_dd,
        "trades": trades,
        "turnover": turnover,
        "hit_rate": hit_rate,
        "cost_pct": cost_pct,
    }


def walk_forward_micro(
    df: pd.DataFrame,
    signal_func,
    n_folds: int = 5,
) -> Dict[str, Any]:
    """Walk-forward validation for microstructure signals."""
    n = len(df)
    fold_size = n // n_folds
    oos_sharpes = []

    for i in range(n_folds):
        start = i * fold_size
        end = min((i + 1) * fold_size, n)
        if end - start < 200:
            continue
        fold_df = df.iloc[start:end].reset_index(drop=True)
        split = int(len(fold_df) * 0.7)
        oos = fold_df.iloc[split:]
        if len(oos) < 50:
            continue
        sig = signal_func(oos)
        r = evaluate_micro_strategy(oos, sig)
        oos_sharpes.append(r["net_sharpe"])

    if not oos_sharpes:
        return {"oos_sharpe": 0, "consistency": 0, "folds": 0}

    avg = np.mean(oos_sharpes)
    pos = sum(1 for s in oos_sharpes if s > 0)
    return {
        "oos_sharpe": float(avg),
        "consistency": float(pos / len(oos_sharpes)),
        "folds": len(oos_sharpes),
    }


def classify_micro_verdict(
    result: Dict[str, Any],
    wf: Dict[str, Any],
    hyp: MicroHypothesis,
) -> Tuple[Verdict, List[str], str]:
    """Classify microstructure hypothesis result."""
    fms = []
    reasons = []
    criteria = hyp.falsification_criteria

    if result["trades"] < 20:
        fms.append("insufficient_trades")
        reasons.append(f"Only {result['trades']} trades")

    if result["net_sharpe"] < 0:
        fms.append("negative_sharpe")
        reasons.append(f"Net Sharpe {result['net_sharpe']:.3f}")

    if result["max_dd"] < criteria.get("max_dd_pct", -15):
        fms.append("catastrophic_drawdown")
        reasons.append(f"Max DD {result['max_dd']:.1f}%")

    if result["net_sharpe"] < criteria.get("min_sharpe", 0.3):
        fms.append("statistical_weakness")
        reasons.append(f"Net Sharpe {result['net_sharpe']:.3f} < {criteria.get('min_sharpe', 0.3)}")

    if result["cost_pct"] > 50:
        fms.append("cost_sensitivity")
        reasons.append(f"Costs {result['cost_pct']:.0f}% of gross")

    if wf.get("consistency", 0) < 0.5 and wf.get("folds", 0) >= 3:
        fms.append("out_of_sample_failure")
        reasons.append(f"WF consistency {wf['consistency']:.0%}")

    if wf.get("oos_sharpe", 0) < 0 and wf.get("folds", 0) >= 3:
        fms.append("oos_negative")
        reasons.append(f"OOS Sharpe {wf['oos_sharpe']:.3f}")

    if wf.get("consistency", 0) < 0.6 and wf.get("folds", 0) >= 3:
        fms.append("regime_instability")

    # Verdict
    if "negative_sharpe" in fms:
        return Verdict.REJECTED, fms, "; ".join(reasons)
    if "catastrophic_drawdown" in fms and "statistical_weakness" in fms:
        return Verdict.REJECTED, fms, "; ".join(reasons)
    if "cost_sensitivity" in fms and len(fms) > 1:
        return Verdict.REJECTED, fms, "; ".join(reasons)
    if "out_of_sample_failure" in fms or "oos_negative" in fms:
        return Verdict.REJECTED, fms, "; ".join(reasons)

    min_s = criteria.get("min_sharpe", 0.3)
    if not fms and result["net_sharpe"] >= min_s and wf.get("consistency", 0) >= 0.6:
        return Verdict.SUPPORTED, fms, "All gates passed"
    if result["net_sharpe"] > 0:
        return Verdict.FRAGILE, fms, "; ".join(reasons) if reasons else "Marginal"
    return Verdict.INCONCLUSIVE, fms, "; ".join(reasons) if reasons else "Insufficient"


# ============================================================
# Campaign 2 Executor
# ============================================================

class MicroCampaignExecutor:
    """Runs Campaign 2 — microstructure/volume hypothesis evaluation."""

    def __init__(self, data: Dict[str, pd.DataFrame], manifest: Any) -> None:
        self._data = data
        self._manifest = manifest

        from .sessions import (
            add_session_features,
            add_realized_volatility_features,
            add_price_structure_features,
        )

        self._prepared: Dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            p = add_session_features(df)
            p = add_realized_volatility_features(p)
            p = add_price_structure_features(p)
            self._prepared[sym] = p

    def run(self) -> List[Dict[str, Any]]:
        """Run all microstructure hypotheses."""
        results = []
        for hyp in ALL_MICRO_HYPOTHESES:
            logger.info(f"  Running {hyp.hypothesis_id}: {hyp.name}")
            r = self._evaluate(hyp)
            results.append(r)
        return results

    def _evaluate(self, hyp: MicroHypothesis) -> Dict[str, Any]:
        asset_results = {}
        asset_sharpes = {}

        for sym, df in self._prepared.items():
            if len(df) < 200:
                continue
            sig = generate_micro_signal(df, hyp)
            r = evaluate_micro_strategy(df, sig)
            asset_results[sym] = r
            asset_sharpes[sym] = r["net_sharpe"]

        if not asset_results:
            return self._empty(hyp)

        # Aggregate
        agg = {k: np.mean([r[k] for r in asset_results.values()])
               for k in ["gross_sharpe", "net_sharpe", "max_dd", "turnover",
                          "hit_rate", "cost_pct"]}
        agg["trades"] = sum(r["trades"] for r in asset_results.values())

        # Walk-forward on symbol with most data
        best_sym = max(self._prepared.keys(),
                       key=lambda s: len(self._prepared[s]))
        sig_func = lambda d: generate_micro_signal(d, hyp)
        wf = walk_forward_micro(self._prepared[best_sym], sig_func)

        verdict, fms, reason = classify_micro_verdict(agg, wf, hyp)

        # Session sharpes
        session_sharpes = {}
        for sess_name in ["asian", "london", "london_ny_overlap", "new_york"]:
            sess_sharpes = []
            for sym, df in self._prepared.items():
                mask = df.get("session_name") == sess_name
                if mask is None or mask.sum() < 50:
                    continue
                sess_df = df[mask].reset_index(drop=True)
                sig = generate_micro_signal(sess_df, hyp)
                r = evaluate_micro_strategy(sess_df, sig)
                sess_sharpes.append(r["net_sharpe"])
            if sess_sharpes:
                session_sharpes[sess_name] = float(np.mean(sess_sharpes))

        return {
            "hypothesis_id": hyp.hypothesis_id,
            "name": hyp.name,
            "signal_source": hyp.signal_source,
            "verdict": verdict.value,
            "gross_sharpe": round(agg["gross_sharpe"], 4),
            "net_sharpe": round(agg["net_sharpe"], 4),
            "oos_sharpe": round(wf["oos_sharpe"], 4),
            "max_dd": round(agg["max_dd"], 2),
            "turnover": round(agg["turnover"], 2),
            "trades": agg["trades"],
            "hit_rate": round(agg["hit_rate"], 4),
            "wf_consistency": round(wf["consistency"], 4),
            "cost_pct": round(agg["cost_pct"], 2),
            "failure_modes": fms,
            "reason": reason,
            "asset_sharpes": {k: round(v, 4) for k, v in asset_sharpes.items()},
            "session_sharpes": {k: round(v, 4) for k, v in session_sharpes.items()},
        }

    def _empty(self, hyp: MicroHypothesis) -> Dict[str, Any]:
        return {
            "hypothesis_id": hyp.hypothesis_id, "name": hyp.name,
            "signal_source": hyp.signal_source,
            "verdict": "inconclusive", "gross_sharpe": 0, "net_sharpe": 0,
            "oos_sharpe": 0, "max_dd": 0, "turnover": 0, "trades": 0,
            "hit_rate": 0, "wf_consistency": 0, "cost_pct": 100,
            "failure_modes": ["insufficient_data"], "reason": "No data",
            "asset_sharpes": {}, "session_sharpes": {},
        }

    def produce_map(self, results: List[Dict[str, Any]]) -> str:
        """Produce Campaign 2 Research Map."""
        by_verdict = {}
        for r in results:
            v = r["verdict"]
            by_verdict.setdefault(v, []).append(r)

        mode_counts = {}
        for r in results:
            for fm in r["failure_modes"]:
                mode_counts[fm] = mode_counts.get(fm, 0) + 1

        lines = [
            "# EigenCapital Intraday Campaign 2 — Microstructure Research Map",
            "",
            "## Context",
            "",
            "**Campaign 1:** 24/24 price-based M5 hypotheses REJECTED (0% survival)",
            "**Campaign 2:** 20 microstructure/volume hypotheses — different information source",
            "",
            "## Campaign Identity",
            "",
            f"**Data Snapshot:** {self._manifest.snapshot_hash}",
            f"**Broker:** {self._manifest.broker} (Terminal {self._manifest.terminal_id})",
            f"**Universe:** {', '.join(self._manifest.symbols)}",
            f"**Timeframe:** M5",
            f"**Total Bars:** {self._manifest.total_bars}",
            f"**Hypotheses Tested:** {len(results)}",
            "",
            "## Verdict Distribution",
            "",
            "```",
        ]

        for verdict in ["supported", "incremental", "fragile", "regime_dependent",
                         "cost_sensitive", "inconclusive", "rejected"]:
            group = by_verdict.get(verdict, [])
            if group:
                bar = "█" * len(group) * 3
                lines.append(f"{verdict.upper():30s} {len(group):3d}  {bar}")

        total = len(results)
        survivors = len(by_verdict.get("supported", [])) + len(by_verdict.get("incremental", []))
        lines.extend(["```", f"**Survival Rate: {survivors/total*100:.1f}%**" if total else "N/A", ""])

        # Failure modes
        lines.extend(["## Failure Mode Distribution", "", "```"])
        for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
            bar = "█" * count * 2
            lines.append(f"{mode:30s} {count:3d}  {bar}")
        lines.extend(["```", ""])

        # Results table
        lines.extend([
            "## Detailed Results",
            "",
            "| ID | Name | Source | Verdict | Net Sharpe | OOS | Max DD | Turnover | WF | Cost% | Failure Modes |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for r in sorted(results, key=lambda x: -x["net_sharpe"]):
            fms = ", ".join(r["failure_modes"][:2]) if r["failure_modes"] else "—"
            lines.append(
                f"| {r['hypothesis_id']} | {r['name'][:30]} | {r['signal_source']} "
                f"| **{r['verdict'].upper()}** | {r['net_sharpe']:.3f} | {r['oos_sharpe']:.3f} "
                f"| {r['max_dd']:.1f}% | {r['turnover']:.1f}x | {r['wf_consistency']:.0%} "
                f"| {r['cost_pct']:.0f}% | {fms} |"
            )

        lines.append("")

        # Survivors
        survivors_list = [r for r in results if r["verdict"] in ("supported", "incremental")]
        if survivors_list:
            lines.extend(["## Survivors — Detailed Analysis", ""])
            for r in survivors_list:
                lines.extend([
                    f"### {r['hypothesis_id']}: {r['name']}",
                    f"- **Signal Source:** {r['signal_source']}",
                    f"- **Net Sharpe:** {r['net_sharpe']:.3f}",
                    f"- **OOS Sharpe:** {r['oos_sharpe']:.3f}",
                    f"- **Max DD:** {r['max_dd']:.1f}%",
                    f"- **Turnover:** {r['turnover']:.1f}x/year",
                    f"- **WF Consistency:** {r['wf_consistency']:.0%}",
                    "",
                    "**Per-Asset Sharpe:**",
                ])
                for sym, sharpe in sorted(r["asset_sharpes"].items(), key=lambda x: -x[1]):
                    lines.append(f"  - {sym}: {sharpe:.3f}")
                lines.extend(["", "**Session Sharpe:**"])
                for sess, sharpe in sorted(r["session_sharpes"].items(), key=lambda x: -x[1]):
                    lines.append(f"  - {sess}: {sharpe:.3f}")
                lines.append("")

        # Rejected
        rejected = [r for r in results if r["verdict"] == "rejected"]
        if rejected:
            lines.extend(["## Rejected — Loser Analysis", ""])
            for r in rejected:
                fms = ", ".join(r["failure_modes"]) if r["failure_modes"] else "unknown"
                lines.append(f"- **{r['hypothesis_id']}** ({r['name']}): {r['reason']} [{fms}]")
            lines.append("")

        lines.extend([
            "## Key Findings",
            "",
            "1. Campaign 2 tests a fundamentally different information source than Campaign 1",
            "2. Volume, spread, and range patterns are tested instead of pure price momentum",
            "3. The research system maintains the same forensic discipline",
            "4. A rejection here means: microstructure signals also don't survive at M5",
            "5. If both Campaign 1 and 2 fail, the conclusion is about the M5 frequency/universe, not the research system",
            "",
            "---",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
            f"Data: {self._manifest.total_bars} bars | Snapshot: {self._manifest.snapshot_hash}*",
        ])

        return "\n".join(lines)
