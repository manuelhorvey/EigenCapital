"""Cross-sectional momentum features.

Computes:
- Cross-sectional rank
- Relative strength
- Percentile rank

These require a UNIVERSE of instruments, which must be explicitly tracked
for provenance. Two apparently identical experiments could use different
asset universes.

Universe tracking:
- universe_id: Identifier for the asset universe
- universe_version: Version of the universe definition
- universe_timestamp: When the universe was defined
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


@dataclass(frozen=True)
class Universe:
    """Asset universe for cross-sectional features.

    Attributes:
        universe_id: Unique identifier
        universe_version: Version string
        universe_timestamp: When the universe was defined
        instruments: List of instrument IDs in the universe
    """

    universe_id: str
    universe_version: str = "v1"
    universe_timestamp: str = ""
    instruments: Tuple = ()

    def __post_init__(self) -> None:
        if not self.universe_id:
            raise ValueError("universe_id must be non-empty")
        if not self.instruments:
            raise ValueError("instruments must not be empty")


def compute_cross_sectional_rank(
    instrument_returns: Dict[str, float],
    target_instrument: str,
) -> Optional[float]:
    """Compute cross-sectional rank of an instrument's return.

    Returns rank as a value between 0 and 1 (percentile).

    Args:
        instrument_returns: Dict mapping instrument → return
        target_instrument: Instrument to rank

    Returns:
        Percentile rank (0 = worst, 1 = best), or None if not in universe
    """
    if target_instrument not in instrument_returns:
        return None

    if len(instrument_returns) < 2:
        return None

    target_return = instrument_returns[target_instrument]
    count_below = sum(1 for r in instrument_returns.values() if r < target_return)
    total = len(instrument_returns)

    return count_below / (total - 1) if total > 1 else 0.5


def compute_relative_strength(
    instrument_returns: Dict[str, float],
    target_instrument: str,
    benchmark_instrument: str,
) -> Optional[float]:
    """Compute relative strength vs benchmark.

    Relative strength = target_return - benchmark_return

    Args:
        instrument_returns: Dict mapping instrument → return
        target_instrument: Target instrument
        benchmark_instrument: Benchmark instrument

    Returns:
        Relative strength, or None if either instrument missing
    """
    if target_instrument not in instrument_returns:
        return None
    if benchmark_instrument not in instrument_returns:
        return None

    return (
        instrument_returns[target_instrument] - instrument_returns[benchmark_instrument]
    )


def compute_percentile_rank(values: List[float], target_value: float) -> float:
    """Compute percentile rank of a value within a list.

    Args:
        values: List of values to rank against
        target_value: Value to rank

    Returns:
        Percentile rank (0 = minimum, 1 = maximum)
    """
    if not values:
        return 0.5

    count_below = sum(1 for v in values if v < target_value)
    count_equal = sum(1 for v in values if v == target_value)

    # Percentile: percentage of values at or below target
    return (count_below + 0.5 * count_equal) / len(values)


def make_cross_sectional_rank_feature(
    instrument_returns: Dict[str, float],
    target_instrument: str,
    universe: Universe,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from cross-sectional rank computation."""
    value = compute_cross_sectional_rank(instrument_returns, target_instrument)
    if value is None:
        return None

    fid = feature_id or f"cs_rank_{target_instrument}_{universe.universe_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=target_instrument,
        timestamp_utc=universe.universe_timestamp,
        value=value,
        feature_family=FeatureFamily.CROSS_SECTIONAL,
        lookback=1,  # Cross-sectional is point-in-time
        source_features=["returns"],
        normalization=Normalization.RANK,
        availability_timestamp=universe.universe_timestamp,
        metadata={
            "universe_id": universe.universe_id,
            "universe_version": universe.universe_version,
            "universe_instruments": sorted(universe.instruments),
        },
    )
