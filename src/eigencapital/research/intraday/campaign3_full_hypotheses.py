"""Campaign 3 Comprehensive Hypothesis Library.

40-60 hypotheses across 9 families, each evaluated at 7 holding horizons.
All hypotheses pre-registered and frozen before evaluation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Hypothesis:
    """Immutable pre-registered hypothesis."""

    hypothesis_id: str
    family: str
    description: str
    signal_func: str
    direction: str  # "long_short" | "long_only" | "short_only"
    economic_rationale: str
    expected_mechanism: str
    data_required: str  # "ohlc" | "volume" | "spread" | "session"
    pre_registered_hash: str = ""

    def compute_hash(self) -> str:
        data = {
            "id": self.hypothesis_id,
            "family": self.family,
            "signal": self.signal_func,
            "direction": self.direction,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


# ── Holding horizons (in M1 bars) ──────────────────────────────────────

HOLDING_HORIZONS = [1, 2, 5, 10, 15, 30, 60]


# ── Family 1: Short-Horizon Price Pressure ──────────────────────────────

FAMILY_1_PRICE_PRESSURE = [
    Hypothesis(
        hypothesis_id="SP-001",
        family="price_pressure",
        description="1-bar directional persistence",
        signal_func="sig_directional_persistence_1",
        direction="long_short",
        economic_rationale="Recent directional pressure creates short-term continuation",
        expected_mechanism="Order flow imbalance drives price in same direction",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-002",
        family="price_pressure",
        description="3-bar signed return accumulation",
        signal_func="sig_return_accum_3",
        direction="long_short",
        economic_rationale="Accumulated short-horizon returns predict next-bar",
        expected_mechanism="Short-term momentum from informed trading",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-003",
        family="price_pressure",
        description="5-bar signed return accumulation",
        signal_func="sig_return_accum_5",
        direction="long_short",
        economic_rationale="5-bar momentum captures micro-persistence",
        expected_mechanism="Order flow pressure builds over multiple bars",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-004",
        family="price_pressure",
        description="Consecutive directional bars (3+)",
        signal_func="sig_consec_direction_3",
        direction="long_short",
        economic_rationale="Consecutive same-direction bars indicate informed pressure",
        expected_mechanism="Informed trading creates streaks",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-005",
        family="price_pressure",
        description="Price acceleration (2nd derivative)",
        signal_func="sig_acceleration",
        direction="long_short",
        economic_rationale="Accelerating moves tend to continue briefly",
        expected_mechanism="Momentum builds as more participants join",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-006",
        family="price_pressure",
        description="Volatility-adjusted impulse",
        signal_func="sig_vol_adjusted_impulse",
        direction="long_short",
        economic_rationale="Large moves relative to recent vol predict continuation",
        expected_mechanism="Volatility-adjusted signal captures abnormal pressure",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-007",
        family="price_pressure",
        description="Return shock reversal (overshoot → revert)",
        signal_func="sig_shock_reversal",
        direction="long_short",
        economic_rationale="Large shocks overshoot and revert",
        expected_mechanism="Market makers absorb shock then price normalizes",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-008",
        family="price_pressure",
        description="Return shock continuation (momentum after shock)",
        signal_func="sig_shock_continuation",
        direction="long_short",
        economic_rationale="Large shocks signal information, not noise",
        expected_mechanism="Informed traders push price further after initial shock",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-009",
        family="price_pressure",
        description="Close-to-midprice divergence",
        signal_func="sig_close_mid_divergence",
        direction="long_short",
        economic_rationale="Bar close vs midprice indicates aggressor direction",
        expected_mechanism="Aggressive buying/selling leaves footprint",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="SP-010",
        family="price_pressure",
        description="High-low range directional bias",
        signal_func="sig_range_direction_bias",
        direction="long_short",
        economic_rationale="Where close sits in bar range indicates directional pressure",
        expected_mechanism="Close near high = buying pressure, near low = selling",
        data_required="ohlc",
    ),
]

# ── Family 2: Microstructure / Tick Activity ────────────────────────────

FAMILY_2_MICROSTRUCTURE = [
    Hypothesis(
        hypothesis_id="MT-001",
        family="microstructure",
        description="Tick volume shock (current/average)",
        signal_func="sig_volume_shock",
        direction="long_short",
        economic_rationale="Abnormal volume indicates institutional activity",
        expected_mechanism="Large volume creates directional pressure",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-002",
        family="microstructure",
        description="Tick volume acceleration",
        signal_func="sig_volume_acceleration",
        direction="long_short",
        economic_rationale="Accelerating volume suggests building interest",
        expected_mechanism="Increasing participation drives price",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-003",
        family="microstructure",
        description="Volume-direction agreement",
        signal_func="sig_volume_direction_agree",
        direction="long_short",
        economic_rationale="Volume in direction of price confirms pressure",
        expected_mechanism="Informed buying with volume confirmation",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-004",
        family="microstructure",
        description="Volume-direction disagreement (contrarian)",
        signal_func="sig_volume_direction_disagree",
        direction="long_short",
        economic_rationale="Volume against price direction signals exhaustion",
        expected_mechanism="Smart money trades against retail momentum",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-005",
        family="microstructure",
        description="High volume + reversal (exhaustion)",
        signal_func="sig_high_vol_reversal",
        direction="long_short",
        economic_rationale="High volume at extremes signals capitulation",
        expected_mechanism="Climactic volume ends move",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-006",
        family="microstructure",
        description="Low volume + breakout (continuation)",
        signal_func="sig_low_vol_breakout",
        direction="long_short",
        economic_rationale="Breakout on low volume may continue quietly",
        expected_mechanism="Orderly accumulation without triggering stops",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="MT-007",
        family="microstructure",
        description="Volume percentile regime",
        signal_func="sig_volume_regime",
        direction="long_short",
        economic_rationale="Volume regime affects predictability of price movement",
        expected_mechanism="Different volume states create different return distributions",
        data_required="volume",
    ),
]

# ── Family 3: Range / Volatility Shocks ────────────────────────────────

FAMILY_3_VOLATILITY = [
    Hypothesis(
        hypothesis_id="VL-001",
        family="volatility",
        description="Range expansion signal",
        signal_func="sig_range_expansion",
        direction="long_short",
        economic_rationale="Sudden range expansion predicts continuation",
        expected_mechanism="Volatility expansion accompanies directional moves",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-002",
        family="volatility",
        description="Range compression → expansion breakout",
        signal_func="sig_range_compression",
        direction="long_short",
        economic_rationale="Compressed ranges precede explosive moves",
        expected_mechanism="Low vol = energy accumulation before expansion",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-003",
        family="volatility",
        description="Volatility-of-volatility signal",
        signal_func="sig_vol_of_vol",
        direction="long_short",
        economic_rationale="Variance of variance predicts regime changes",
        expected_mechanism="Volatile vol regimes create directional opportunities",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-004",
        family="volatility",
        description="Realized vol vs average (regime)",
        signal_func="sig_realized_vol_regime",
        direction="long_short",
        economic_rationale="Volatility mean-reverts; regime affects returns",
        expected_mechanism="High vol periods precede directional moves",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-005",
        family="volatility",
        description="Volatility shock continuation",
        signal_func="sig_vol_shock_continue",
        direction="long_short",
        economic_rationale="Volatility shocks persist briefly",
        expected_mechanism="Vol clustering creates exploitable persistence",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-006",
        family="volatility",
        description="Volatility shock reversal",
        signal_func="sig_vol_shock_revert",
        direction="long_short",
        economic_rationale="Extreme vol shocks revert as market calms",
        expected_mechanism="Overshoot in vol normalizes, price follows",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="VL-007",
        family="volatility",
        description="True range relative to average",
        signal_func="sig_true_range_relative",
        direction="long_short",
        economic_rationale="Abnormal true range signals potential directional move",
        expected_mechanism="Large range bars indicate information arrival",
        data_required="ohlc",
    ),
]

# ── Family 4: Liquidity / Spread State ─────────────────────────────────

FAMILY_4_LIQUIDITY = [
    Hypothesis(
        hypothesis_id="LQ-001",
        family="liquidity",
        description="Spread expansion signal",
        signal_func="sig_spread_expansion",
        direction="long_short",
        economic_rationale="Spread widening reduces liquidity, creates dislocation",
        expected_mechanism="Reduced liquidity allows price overshoot",
        data_required="spread",
    ),
    Hypothesis(
        hypothesis_id="LQ-002",
        family="liquidity",
        description="Spread compression signal",
        signal_func="sig_spread_compression",
        direction="long_short",
        economic_rationale="Tight spreads indicate confidence, may precede moves",
        expected_mechanism="High liquidity = orderly market = predictable moves",
        data_required="spread",
    ),
    Hypothesis(
        hypothesis_id="LQ-003",
        family="liquidity",
        description="Spread normalization after shock",
        signal_func="sig_spread_normalize",
        direction="long_short",
        economic_rationale="Price tends to revert after spread normalizes",
        expected_mechanism="Liquidity returns, price adjusts to fair value",
        data_required="spread",
    ),
    Hypothesis(
        hypothesis_id="LQ-004",
        family="liquidity",
        description="Abnormal spread relative to history",
        signal_func="sig_abnormal_spread",
        direction="long_short",
        economic_rationale="Spread far from normal signals unusual conditions",
        expected_mechanism="Abnormal conditions create temporary dislocations",
        data_required="spread",
    ),
    Hypothesis(
        hypothesis_id="LQ-005",
        family="liquidity",
        description="Liquidity shock + price continuation",
        signal_func="sig_liquidity_shock_continue",
        direction="long_short",
        economic_rationale="Liquidity shocks accompanied by price direction persist",
        expected_mechanism="Large orders consume liquidity, push price further",
        data_required="spread",
    ),
    Hypothesis(
        hypothesis_id="LQ-006",
        family="liquidity",
        description="Liquidity shock + reversal",
        signal_func="sig_liquidity_shock_revert",
        direction="long_short",
        economic_rationale="Liquidity shocks overshoot and revert",
        expected_mechanism="Temporary liquidity vacuum normalizes",
        data_required="spread",
    ),
]

# ── Family 5: Session Transitions ──────────────────────────────────────

FAMILY_5_SESSIONS = [
    Hypothesis(
        hypothesis_id="SS-001",
        family="sessions",
        description="Asian→London transition momentum",
        signal_func="sig_asia_london_transition",
        direction="long_short",
        economic_rationale="London open inherits Asia session direction",
        expected_mechanism="Accumulated overnight orders flow into London",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-002",
        family="sessions",
        description="London open impulse",
        signal_func="sig_london_open_impulse",
        direction="long_short",
        economic_rationale="London open creates directional impulse",
        expected_mechanism="Market makers establish opening price",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-003",
        family="sessions",
        description="London→New York transition",
        signal_func="sig_london_ny_transition",
        direction="long_short",
        economic_rationale="NY open may continue or reverse London direction",
        expected_mechanism="US participants react to European session",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-004",
        family="sessions",
        description="New York open impulse",
        signal_func="sig_ny_open_impulse",
        direction="long_short",
        economic_rationale="US market open creates significant directional move",
        expected_mechanism="US institutional flow dominates",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-005",
        family="sessions",
        description="London/NY overlap momentum",
        signal_func="sig_overlap_momentum",
        direction="long_short",
        economic_rationale="Overlap is most active session, trends strongest",
        expected_mechanism="Dual-session participation amplifies direction",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-006",
        family="sessions",
        description="NY close mean-reversion",
        signal_func="sig_ny_close_revert",
        direction="long_short",
        economic_rationale="End-of-day positions flatten, creating mean reversion",
        expected_mechanism="Profit-taking and position squaring at close",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-007",
        family="sessions",
        description="Session range breakout",
        signal_func="sig_session_range_breakout",
        direction="long_short",
        economic_rationale="Breaking session high/low signals continuation",
        expected_mechanism="Stop cascades beyond session extremes",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="SS-008",
        family="sessions",
        description="Overnight gap fill vs continuation",
        signal_func="sig_overnight_gap",
        direction="long_short",
        economic_rationale="Gaps may fill (reversion) or extend (information)",
        expected_mechanism="Gap content determines direction",
        data_required="session",
    ),
]

# ── Family 6: Opening / Initial Range ──────────────────────────────────

FAMILY_6_OPENING = [
    Hypothesis(
        hypothesis_id="OR-001",
        family="opening",
        description="Initial range breakout (first 15 bars)",
        signal_func="sig_initial_range_breakout",
        direction="long_short",
        economic_rationale="Breaking initial range signals directional intent",
        expected_mechanism="Informed traders establish direction early",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="OR-002",
        family="opening",
        description="Initial range reversal (false breakout)",
        signal_func="sig_initial_range_reversal",
        direction="long_short",
        economic_rationale="Failed breakout of initial range triggers reversal",
        expected_mechanism="Stops hit, trapped traders exit",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="OR-003",
        family="opening",
        description="Opening impulse (first 5 bars direction)",
        signal_func="sig_opening_impulse",
        direction="long_short",
        economic_rationale="Opening bars reflect overnight accumulation",
        expected_mechanism="Directional order flow at open",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="OR-004",
        family="opening",
        description="Opening reversal (impulse then revert)",
        signal_func="sig_opening_reversal",
        direction="long_short",
        economic_rationale="Opening moves often overshoot and revert",
        expected_mechanism="Market makers manipulate opening price",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="OR-005",
        family="opening",
        description="Prior session range vs current direction",
        signal_func="sig_prior_range_direction",
        direction="long_short",
        economic_rationale="Relationship to prior session range predicts direction",
        expected_mechanism="Range position indicates institutional positioning",
        data_required="session",
    ),
]

# ── Family 7: Cross-Asset Lead/Lag ─────────────────────────────────────

FAMILY_7_CROSS_ASSET = [
    Hypothesis(
        hypothesis_id="XA-001",
        family="cross_asset",
        description="US500 leads EURUSD (1-5 min lag)",
        signal_func="sig_us500_leads_eurusd",
        direction="long_short",
        economic_rationale="US equity leads risk-sensitive FX",
        expected_mechanism="Equity price movement precedes FX adjustment",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="XA-002",
        family="cross_asset",
        description="USTEC leads EURUSD (1-5 min lag)",
        signal_func="sig_ustec_leads_eurusd",
        direction="long_short",
        economic_rationale="Tech index leads risk sentiment in FX",
        expected_mechanism="USTEC movement reflects risk appetite",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="XA-003",
        family="cross_asset",
        description="US500 leads GBPUSD (1-5 min lag)",
        signal_func="sig_us500_leads_gbpusd",
        direction="long_short",
        economic_rationale="Equity leads GBP as risk currency",
        expected_mechanism="Risk-on/off flows transmit from equities to FX",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="XA-004",
        family="cross_asset",
        description="USTEC leads XAUUSD (1-5 min lag)",
        signal_func="sig_ustec_leads_xauusd",
        direction="long_short",
        economic_rationale="Tech weakness → safe haven → gold up",
        expected_mechanism="Risk-off flow moves gold inversely to equities",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="XA-005",
        family="cross_asset",
        description="US500 leads XAUUSD (1-5 min lag)",
        signal_func="sig_us500_leads_xauusd",
        direction="long_short",
        economic_rationale="Equity weakness → gold rally",
        expected_mechanism="Flight to safety from equities to gold",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="XA-006",
        family="cross_asset",
        description="EURUSD leads GBPUSD (1-3 min lag)",
        signal_func="sig_eurusd_leads_gbpusd",
        direction="long_short",
        economic_rationale="EUR/USD is benchmark, GBP follows with lag",
        expected_mechanism="EURUSD price discovery precedes GBP adjustment",
        data_required="ohlc",
    ),
]

# ── Family 8: Event-Driven Response ────────────────────────────────────

FAMILY_8_EVENTS = [
    Hypothesis(
        hypothesis_id="EV-001",
        family="events",
        description="Pre-session volatility compression",
        signal_func="sig_pre_session_compression",
        direction="long_short",
        economic_rationale="Volatility compresses before session open",
        expected_mechanism="Market holds breath before new session",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="EV-002",
        family="events",
        description="Post-shock impulse continuation",
        signal_func="sig_post_shock_impulse",
        direction="long_short",
        economic_rationale="Large moves create follow-through",
        expected_mechanism="Momentum from shock attracts trend followers",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="EV-003",
        family="events",
        description="Post-shock reversal",
        signal_func="sig_post_shock_reversal",
        direction="long_short",
        economic_rationale="Large shocks overshoot and revert",
        expected_mechanism="Mean reversion after overreaction",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="EV-004",
        family="events",
        description="Volatility normalization after event",
        signal_func="sig_vol_normalization",
        direction="long_short",
        economic_rationale="Vol normalizes after event, creating predictable path",
        expected_mechanism="Vol mean-reversion creates directional opportunities",
        data_required="ohlc",
    ),
]

# ── Family 9: Conditional Combinations ─────────────────────────────────

FAMILY_9_COMBINATIONS = [
    Hypothesis(
        hypothesis_id="CM-001",
        family="combinations",
        description="Momentum + vol regime (high vol = stronger signal)",
        signal_func="sig_mom_x_vol",
        direction="long_short",
        economic_rationale="Momentum works better in volatile regimes",
        expected_mechanism="High vol amplifies momentum persistence",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="CM-002",
        family="combinations",
        description="Shock + session (shock in overlap = stronger)",
        signal_func="sig_shock_x_session",
        direction="long_short",
        economic_rationale="Shocks during active sessions have follow-through",
        expected_mechanism="Dual-session participation amplifies shock response",
        data_required="session",
    ),
    Hypothesis(
        hypothesis_id="CM-003",
        family="combinations",
        description="Range expansion + volume (breakout confirmation)",
        signal_func="sig_rangeexp_x_volume",
        direction="long_short",
        economic_rationale="Range expansion confirmed by volume = genuine move",
        expected_mechanism="Volume confirms breakout is real, not noise",
        data_required="volume",
    ),
    Hypothesis(
        hypothesis_id="CM-004",
        family="combinations",
        description="Cross-asset lead + vol regime",
        signal_func="sig_xa_lead_x_vol",
        direction="long_short",
        economic_rationale="Cross-asset leads work better in calm vol",
        expected_mechanism="Low vol allows cleaner transmission of information",
        data_required="ohlc",
    ),
    Hypothesis(
        hypothesis_id="CM-005",
        family="combinations",
        description="Spread shock + price direction",
        signal_func="sig_spread_x_direction",
        direction="long_short",
        economic_rationale="Spread widening in trending market = continuation",
        expected_mechanism="Illiquidity amplifies existing trend",
        data_required="spread",
    ),
]

# ── Combine all families ───────────────────────────────────────────────

ALL_HYPOTHESES: List[Hypothesis] = (
    FAMILY_1_PRICE_PRESSURE
    + FAMILY_2_MICROSTRUCTURE
    + FAMILY_3_VOLATILITY
    + FAMILY_4_LIQUIDITY
    + FAMILY_5_SESSIONS
    + FAMILY_6_OPENING
    + FAMILY_7_CROSS_ASSET
    + FAMILY_8_EVENTS
    + FAMILY_9_COMBINATIONS
)

# Pre-compute hashes
for hyp in ALL_HYPOTHESES:
    object.__setattr__(hyp, "pre_registered_hash", hyp.compute_hash())

# Family summary
FAMILY_SUMMARY = {
    "price_pressure": len(FAMILY_1_PRICE_PRESSURE),
    "microstructure": len(FAMILY_2_MICROSTRUCTURE),
    "volatility": len(FAMILY_3_VOLATILITY),
    "liquidity": len(FAMILY_4_LIQUIDITY),
    "sessions": len(FAMILY_5_SESSIONS),
    "opening": len(FAMILY_6_OPENING),
    "cross_asset": len(FAMILY_7_CROSS_ASSET),
    "events": len(FAMILY_8_EVENTS),
    "combinations": len(FAMILY_9_COMBINATIONS),
}
