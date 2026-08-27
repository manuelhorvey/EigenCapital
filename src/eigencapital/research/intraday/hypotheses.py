"""Intraday Hypothesis Library — pre-registered hypotheses for the first campaign.

Phase I-D through I-K: Hypothesis families and definitions.

Every hypothesis is frozen and immutable once registered.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


class HypothesisFamily(Enum):
    MOMENTUM = "momentum"
    REVERSAL = "reversal"
    BREAKOUT = "breakout"
    VOLATILITY = "volatility"
    SESSION = "session"
    CROSS_ASSET = "cross_asset"
    MEAN_REVERSION = "mean_reversion"
    STRUCTURE = "structure"
    ML_CHALLENGER = "ml_challenger"


class HoldingPeriod(Enum):
    M5 = "5min"
    M15 = "15min"
    M30 = "30min"
    H1 = "1hour"
    H2 = "2hour"
    SESSION_CLOSE = "session_close"


class Verdict(Enum):
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    FRAGILE = "fragile"
    COST_SENSITIVE = "cost_sensitive"
    EXECUTION_SENSITIVE = "execution_sensitive"
    REGIME_DEPENDENT = "regime_dependent"
    CAPACITY_LIMITED = "capacity_limited"
    REDUNDANT = "redundant"
    SUPPORTED = "supported"
    INCREMENTAL = "incremental"
    PRODUCTION_CANDIDATE = "production_candidate"


@dataclass(frozen=True)
class HypothesisDefinition:
    """Immutable hypothesis definition — frozen at registration time."""

    hypothesis_id: str
    family: HypothesisFamily
    name: str
    description: str
    economic_rationale: str
    base_timeframe: str
    holding_period: HoldingPeriod
    signal_type: str  # "directional" or "magnitude"
    lookback_bars: int
    entry_logic: str
    exit_logic: str
    falsification_criteria: Dict[str, Any]
    cost_sensitivity: str  # "low", "medium", "high"
    dependency: str | None = None  # parent hypothesis_id
    is_incremental: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family.value,
            "name": self.name,
            "description": self.description,
            "economic_rationale": self.economic_rationale,
            "base_timeframe": self.base_timeframe,
            "holding_period": self.holding_period.value,
            "signal_type": self.signal_type,
            "lookback_bars": self.lookback_bars,
            "entry_logic": self.entry_logic,
            "exit_logic": self.exit_logic,
            "falsification_criteria": self.falsification_criteria,
            "cost_sensitivity": self.cost_sensitivity,
            "dependency": self.dependency,
            "is_incremental": self.is_incremental,
        }

    @property
    def fingerprint(self) -> str:
        """Deterministic hash of hypothesis definition."""
        data = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


# ============================================================
# TIER 1: Simple Micro/Intraday Effects
# ============================================================

HYPOTHESIS_MOM_001 = HypothesisDefinition(
    hypothesis_id="ID-MOM-001",
    family=HypothesisFamily.MOMENTUM,
    name="Short-Horizon Intraday Momentum",
    description="5-minute continuation: if last N bars were up, expect next bar up",
    economic_rationale="Order flow persistence and short-term information diffusion",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M5,
    signal_type="directional",
    lookback_bars=12,  # 1 hour
    entry_logic="long if sum(close>open) over lookback > threshold, short if < threshold",
    exit_logic="opposite signal or time-based exit",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="high",
)

HYPOTHESIS_MOM_002 = HypothesisDefinition(
    hypothesis_id="ID-MOM-002",
    family=HypothesisFamily.MOMENTUM,
    name="Medium-Horizon Intraday Momentum",
    description="3-hour continuation: 36-bar lookback momentum",
    economic_rationale="Intraday trend persistence from institutional order flow",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=36,
    entry_logic="long if 36-bar return > 0, short if < 0, scaled by volatility",
    exit_logic="opposite signal or session-close exit",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_MOM_003 = HypothesisDefinition(
    hypothesis_id="ID-MOM-003",
    family=HypothesisFamily.MOMENTUM,
    name="Session Momentum Persistence",
    description="If morning session was bullish, afternoon tends to continue",
    economic_rationale="Institutional rebalancing and continuation of intraday flows",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H2,
    signal_type="directional",
    lookback_bars=72,  # ~6 hours
    entry_logic="long if session-to-date return > 0 and volume confirms",
    exit_logic="session-close or reversal signal",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -20.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_REV_001 = HypothesisDefinition(
    hypothesis_id="ID-REV-001",
    family=HypothesisFamily.REVERSAL,
    name="Short-Term Mean Reversion",
    description="Extreme 5-bar moves tend to revert within 3 bars",
    economic_rationale="Overreaction and mean reversion in liquid FX markets",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=5,
    entry_logic="short if z-score(5-bar return) > 2, long if < -2",
    exit_logic="mean reversion to 0 or 3-bar timeout",
    falsification_criteria={"min_sharpe": 0.2, "max_dd_pct": -10.0},
    cost_sensitivity="high",
)

HYPOTHESIS_REV_002 = HypothesisDefinition(
    hypothesis_id="ID-REV-002",
    family=HypothesisFamily.REVERSAL,
    name="Intraday Exhaustion Reversal",
    description="Late-session extreme moves tend to reverse next session",
    economic_rationale="End-of-day position squaring and overnight gap reversal",
    base_timeframe="M5",
    holding_period=HoldingPeriod.SESSION_CLOSE,
    signal_type="directional",
    lookback_bars=36,
    entry_logic="short if last-hour return > 2*vol, long if < -2*vol",
    exit_logic="next session open or time-based",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_VOL_001 = HypothesisDefinition(
    hypothesis_id="ID-VOL-001",
    family=HypothesisFamily.VOLATILITY,
    name="Volatility Expansion Breakout",
    description="Low-volatility compression followed by expansion predicts directional move",
    economic_rationale="Volatility clustering and regime transitions",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=36,
    entry_logic="long if ATR(12)/ATR(36) < 0.5 and next-bar breakout above range",
    exit_logic="opposite breakout or 2*ATR stop",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_VOL_002 = HypothesisDefinition(
    hypothesis_id="ID-VOL-002",
    family=HypothesisFamily.VOLATILITY,
    name="Volatility Contraction Fade",
    description="Trade against moves in low-volatility regimes",
    economic_rationale="Low-vol regimes produce mean-reverting price action",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=72,
    entry_logic="short if move > 1.5*ATR and ATR rank < 30th percentile",
    exit_logic="mean reversion or 1.5*ATR stop",
    falsification_criteria={"min_sharpe": 0.2, "max_dd_pct": -12.0},
    cost_sensitivity="high",
)

HYPOTHESIS_BRK_001 = HypothesisDefinition(
    hypothesis_id="ID-BRK-001",
    family=HypothesisFamily.BREAKOUT,
    name="Opening Range Breakout",
    description="Breakout from first 30-minute range predicts direction",
    economic_rationale="Opening range captures overnight information and institutional positioning",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H1,
    signal_type="directional",
    lookback_bars=6,  # 30 minutes
    entry_logic="long if price breaks above opening range high, short if below low",
    exit_logic="opposite range break or session-close",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_BRK_002 = HypothesisDefinition(
    hypothesis_id="ID-BRK-002",
    family=HypothesisFamily.BREAKOUT,
    name="Session High/Low Breakout",
    description="Breakout from previous session's high/low predicts continuation",
    economic_rationale="Key levels attract stop orders and institutional activity",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H2,
    signal_type="directional",
    lookback_bars=72,
    entry_logic="long if close > prev_session_high, short if < prev_session_low",
    exit_logic="opposite break or 2*ATR trailing stop",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_BRK_003 = HypothesisDefinition(
    hypothesis_id="ID-BRK-003",
    family=HypothesisFamily.BREAKOUT,
    name="Range Compression Breakout",
    description="Tight Bollinger Band squeeze predicts expansion",
    economic_rationale="Volatility clustering and regime transition",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=36,
    entry_logic="long if BB_width < 20th percentile and close > upper_band",
    exit_logic="close back inside bands or 2*ATR stop",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)


# ============================================================
# TIER 2: Session Structure
# ============================================================

HYPOTHESIS_SES_001 = HypothesisDefinition(
    hypothesis_id="ID-SES-001",
    family=HypothesisFamily.SESSION,
    name="London Open Momentum",
    description="Directional move in first hour of London session persists",
    economic_rationale="London open captures overnight information and sets daily tone",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H2,
    signal_type="directional",
    lookback_bars=12,  # 1 hour
    entry_logic="long if London open hour return > 0 and volume above average",
    exit_logic="NY overlap or session-close",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

HYPOTHESIS_SES_002 = HypothesisDefinition(
    hypothesis_id="ID-SES-002",
    family=HypothesisFamily.SESSION,
    name="NY Open Momentum",
    description="Directional move in first hour of NY session persists",
    economic_rationale="US market open captures overnight information flow",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H2,
    signal_type="directional",
    lookback_bars=12,
    entry_logic="long if NY open hour return > 0 and US futures trending",
    exit_logic="NY close or time-based",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

HYPOTHESIS_SES_003 = HypothesisDefinition(
    hypothesis_id="ID-SES-003",
    family=HypothesisFamily.SESSION,
    name="London-NY Overlap Continuation",
    description="Moves during overlap period have highest persistence",
    economic_rationale="Overlap has highest liquidity and institutional participation",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H1,
    signal_type="directional",
    lookback_bars=12,
    entry_logic="long if overlap-period trend > 0 and spread tight",
    exit_logic="NY close or reversal",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="low",
)

HYPOTHESIS_SES_004 = HypothesisDefinition(
    hypothesis_id="ID-SES-004",
    family=HypothesisFamily.SESSION,
    name="Asian Range Breakout at London Open",
    description="Breakout from Asian session range at London open",
    economic_rationale="Asian range sets support/resistance for European session",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H1,
    signal_type="directional",
    lookback_bars=84,  # full Asian session
    entry_logic="long if London open breaks above Asian high, short if below low",
    exit_logic="1.5*Asian range or session-close",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)


# ============================================================
# TIER 3: Price Structure
# ============================================================

HYPOTHESIS_STR_001 = HypothesisDefinition(
    hypothesis_id="ID-STR-001",
    family=HypothesisFamily.STRUCTURE,
    name="VWAP Deviation Reversion",
    description="Price deviation from intraday VWAP tends to revert",
    economic_rationale="VWAP represents fair value for institutional execution",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=0,  # uses VWAP, not lookback
    entry_logic="short if close > 2*sigma above VWAP, long if below",
    exit_logic="revert to VWAP or session-close",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -12.0},
    cost_sensitivity="high",
)

HYPOTHESIS_STR_002 = HypothesisDefinition(
    hypothesis_id="ID-STR-002",
    family=HypothesisFamily.STRUCTURE,
    name="Range Position Mean Reversion",
    description="Price at extremes of daily range tends to revert toward middle",
    economic_rationale="Range-bound markets exhibit mean-reverting behavior",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=144,  # ~12 hours
    entry_logic="short if range_position > 0.9, long if < 0.1",
    exit_logic="range_position returns to 0.4-0.6 zone",
    falsification_criteria={"min_sharpe": 0.2, "max_dd_pct": -12.0},
    cost_sensitivity="high",
)

HYPOTHESIS_STR_003 = HypothesisDefinition(
    hypothesis_id="ID-STR-003",
    family=HypothesisFamily.STRUCTURE,
    name="Previous Day High/Low Rejection",
    description="Price touching prior day's high/low and failing signals reversal",
    economic_rationale="Key institutional levels create supply/demand zones",
    base_timeframe="M5",
    holding_period=HoldingPeriod.H1,
    signal_type="directional",
    lookback_bars=288,  # prior day
    entry_logic="short if touched prev_day_high and closed below, long if opposite",
    exit_logic="opposite level or 2*ATR stop",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)


# ============================================================
# TIER 4: Cross-Asset Lead/Lag
# ============================================================

HYPOTHESIS_XA_001 = HypothesisDefinition(
    hypothesis_id="ID-XA-001",
    family=HypothesisFamily.CROSS_ASSET,
    name="US500 Leads USTEC",
    description="S&P 500 moves lead Nasdaq with 5-10 min delay",
    economic_rationale="Large-cap flows precede tech flows in opening rotation",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=2,  # 10 min lag
    entry_logic="long USTEC if US500 moved > threshold in last 2 bars",
    exit_logic="convergence or 3-bar timeout",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -12.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_XA_002 = HypothesisDefinition(
    hypothesis_id="ID-XA-002",
    family=HypothesisFamily.CROSS_ASSET,
    name="USD Strength Leads XAUUSD",
    description="Dollar index strength leads gold weakness with delay",
    economic_rationale="Gold is priced in USD and inversely correlated",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=6,
    entry_logic="short XAUUSD if composite USD strength > threshold",
    exit_logic="convergence or session-close",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)

HYPOTHESIS_XA_003 = HypothesisDefinition(
    hypothesis_id="ID-XA-003",
    family=HypothesisFamily.CROSS_ASSET,
    name="USOIL Leads CAD",
    description="Oil price moves lead USDCAD with delay",
    economic_rationale="CAD is a petrocurrency with strong oil correlation",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=6,
    entry_logic="short USDCAD if USOIL moved > threshold in last 6 bars",
    exit_logic="convergence or session-close",
    falsification_criteria={"min_sharpe": 0.2, "max_dd_pct": -12.0},
    cost_sensitivity="medium",
    dependency="ID-XA-002",
    is_incremental=True,
)


# ============================================================
# TIER 5: Volatility Conditioning
# ============================================================

HYPOTHESIS_VCOND_001 = HypothesisDefinition(
    hypothesis_id="ID-VCOND-001",
    family=HypothesisFamily.VOLATILITY,
    name="High-Vol Momentum Dampening",
    description="Reduce momentum exposure in high-volatility regimes",
    economic_rationale="Momentum works better in trending, low-to-moderate vol environments",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="magnitude",
    lookback_bars=36,
    entry_logic="reduce position size by 50% if RV rank > 80th percentile",
    exit_logic="normal exit with dampened size",
    falsification_criteria={"min_sharpe": 0.2, "max_dd_pct": -10.0},
    cost_sensitivity="low",
    dependency="ID-MOM-001",
    is_incremental=True,
)

HYPOTHESIS_VCOND_002 = HypothesisDefinition(
    hypothesis_id="ID-VCOND-002",
    family=HypothesisFamily.VOLATILITY,
    name="Volatility Regime Switching",
    description="Trade different strategies in different vol regimes",
    economic_rationale="Different market microstructure dominates in different vol regimes",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="magnitude",
    lookback_bars=72,
    entry_logic="momentum in low-vol regime, mean-reversion in high-vol regime",
    exit_logic="regime change or time-based",
    falsification_criteria={"min_sharpe": 0.4, "max_dd_pct": -15.0},
    cost_sensitivity="medium",
)


# ============================================================
# TIER 6: Mean Reversion (Hostile Cost Testing Required)
# ============================================================

HYPOTHESIS_MR_001 = HypothesisDefinition(
    hypothesis_id="ID-MR-001",
    family=HypothesisFamily.MEAN_REVERSION,
    name="Intraday Displacement Reversion",
    description="Extreme displacement from intraday mean reverts within session",
    economic_rationale="Overreaction and liquidity provision create reversion opportunities",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M30,
    signal_type="directional",
    lookback_bars=24,  # 2 hours
    entry_logic="short if z-score(24-bar return) > 2.5, long if < -2.5",
    exit_logic="z-score returns to 0 or 4-bar timeout",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -10.0},
    cost_sensitivity="very_high",
)

HYPOTHESIS_MR_002 = HypothesisDefinition(
    hypothesis_id="ID-MR-002",
    family=HypothesisFamily.MEAN_REVERSION,
    name="Failed Breakout Reversal",
    description="Failed breakout attempts reverse sharply",
    economic_rationale="Trapped breakout traders create cascading reversals",
    base_timeframe="M5",
    holding_period=HoldingPeriod.M15,
    signal_type="directional",
    lookback_bars=12,
    entry_logic="short if broke above 12-bar high then closed back below",
    exit_logic="time-based or opposite signal",
    falsification_criteria={"min_sharpe": 0.3, "max_dd_pct": -12.0},
    cost_sensitivity="high",
)


# ============================================================
# REGISTRY
# ============================================================

ALL_HYPOTHESES: List[HypothesisDefinition] = [
    # Tier 1: Simple effects
    HYPOTHESIS_MOM_001,
    HYPOTHESIS_MOM_002,
    HYPOTHESIS_MOM_003,
    HYPOTHESIS_REV_001,
    HYPOTHESIS_REV_002,
    HYPOTHESIS_VOL_001,
    HYPOTHESIS_VOL_002,
    HYPOTHESIS_BRK_001,
    HYPOTHESIS_BRK_002,
    HYPOTHESIS_BRK_003,
    # Tier 2: Session structure
    HYPOTHESIS_SES_001,
    HYPOTHESIS_SES_002,
    HYPOTHESIS_SES_003,
    HYPOTHESIS_SES_004,
    # Tier 3: Price structure
    HYPOTHESIS_STR_001,
    HYPOTHESIS_STR_002,
    HYPOTHESIS_STR_003,
    # Tier 4: Cross-asset
    HYPOTHESIS_XA_001,
    HYPOTHESIS_XA_002,
    HYPOTHESIS_XA_003,
    # Tier 5: Volatility conditioning
    HYPOTHESIS_VCOND_001,
    HYPOTHESIS_VCOND_002,
    # Tier 6: Mean reversion
    HYPOTHESIS_MR_001,
    HYPOTHESIS_MR_002,
]

HYPOTHESIS_REGISTRY: Dict[str, HypothesisDefinition] = {h.hypothesis_id: h for h in ALL_HYPOTHESES}


def get_hypothesis(hypothesis_id: str) -> HypothesisDefinition:
    """Get hypothesis by ID. Raises KeyError if not found."""
    if hypothesis_id not in HYPOTHESIS_REGISTRY:
        raise KeyError(f"Hypothesis {hypothesis_id} not registered")
    return HYPOTHESIS_REGISTRY[hypothesis_id]


def get_hypotheses_by_family(family: HypothesisFamily) -> List[HypothesisDefinition]:
    """Get all hypotheses in a family."""
    return [h for h in ALL_HYPOTHESES if h.family == family]


def compute_library_hash() -> str:
    """Compute deterministic hash of the entire hypothesis library."""
    data = json.dumps([h.to_dict() for h in ALL_HYPOTHESES], sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]
