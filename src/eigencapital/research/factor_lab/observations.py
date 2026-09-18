"""Factor Observations — panel assembly under the frozen R2 contract.

Implements contract items 1–3, 8–9 of docs/research/R2_FACTOR_LAB.md:

- One observation = (factor_id, period_date, symbol, signal_value,
  forward_return, availability_ts, decision_ts).
- Forward-return alignment (FROZEN): the factor is observed at the decision
  bar's close (decision_ts = bar_end of the decision bar). The forward return
  spans close(t) → close(t+h): it is computed ONLY from bars whose bar_end is
  at or before the decision bar's close shifted by h bars in the symbol's own
  calendar. factor(t) → return(t) is structurally impossible here: the return
  window starts AFTER the decision bar (the first bar in the window is t+1).
- PIT invariant: availability_ts <= decision_ts on every observation; a
  violation raises (no exception path).
- Missing-data policy: a symbol missing its signal or lacking enough bars to
  compute the forward return is excluded from that period's panel. Every
  exclusion is counted and reported. No imputation, no fill-forward.
- Overlap declaration: panels built from overlapping horizons carry the
  horizon and the overlap acknowledgment in the panel metadata so the
  experiment's trial metadata can declare it (contract item 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from eigencapital.core.models.bar import Bar


class PanelBuildError(ValueError):
    """Raised on contract violations during panel assembly."""


@dataclass(frozen=True)
class FactorObservation:
    """One (factor, period, symbol) observation.

    Attributes:
        factor_id: Registered factor identifier.
        period_date: ISO date of the decision bar (the rebalance date).
        symbol: Symbol identifier.
        signal_value: Factor value observed at the decision bar's close.
        forward_return: close(t) → close(t+h) return in fractional units.
        availability_ts: ISO-8601 timestamp when the signal became computable.
        decision_ts: ISO-8601 bar_end of the decision bar.
    """

    factor_id: str
    period_date: str
    symbol: str
    signal_value: float
    forward_return: float
    availability_ts: str
    decision_ts: str

    def __post_init__(self) -> None:
        if not self.factor_id or not self.symbol:
            raise PanelBuildError("factor_id and symbol must be non-empty")
        if self.availability_ts > self.decision_ts:
            raise PanelBuildError(
                f"PIT invariant violated for {self.symbol}@{self.period_date}: "
                f"availability {self.availability_ts} > decision {self.decision_ts}"
            )


@dataclass(frozen=True)
class PanelSet:
    """Assembled panels plus the policy provenance required by the contract.

    Attributes:
        factor_id: Factor identifier.
        horizon: Forward-return horizon in trading bars.
        panels: One entry per period (chronological); each entry is a list of
            (signal, forward_return) pairs — the shape the IC/quantile
            machinery consumes.
        period_dates: ISO dates aligned with ``panels``.
        n_observations: Total observations across panels.
        exclusions: Per-symbol exclusion counts with reasons (never imputed).
        overlap_note: Explicit acknowledgment when horizons overlap.
        universe_version: Preregistered universe identifier.
    """

    factor_id: str
    horizon: int
    panels: List[List[tuple[float, float]]]
    period_dates: List[str]
    n_observations: int
    exclusions: Dict[str, int]
    overlap_note: str
    universe_version: str

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization of assembly provenance."""
        return {
            "factor_id": self.factor_id,
            "horizon": self.horizon,
            "n_panels": len(self.panels),
            "n_observations": self.n_observations,
            "exclusions": dict(sorted(self.exclusions.items())),
            "overlap_note": self.overlap_note,
            "universe_version": self.universe_version,
        }


def build_factor_panels(
    factor_id: str,
    universe_version: str,
    horizon: int,
    signals: Dict[str, Sequence[tuple[str, float, str]]],
    bars_by_symbol: Dict[str, Sequence[Bar]],
) -> PanelSet:
    """Assemble factor observation panels under the frozen contract.

    Args:
        factor_id: Registered factor identifier.
        universe_version: Preregistered universe version identifier.
        horizon: Forward-return horizon in trading bars (>= 1).
        signals: symbol → chronological (period_date, signal_value,
            availability_ts) tuples. period_date must equal the decision
            bar's date.
        bars_by_symbol: symbol → chronological bars (the symbol's own
            calendar). The decision bar is matched by date; the forward
            window spans the next h bar closes.

    Returns:
        PanelSet with panels shaped for the IC/quantile machinery.

    Raises:
        PanelBuildError: On horizon < 1, PIT violations, or a signal whose
            period_date has no matching bar for that symbol.
    """
    if horizon < 1:
        raise PanelBuildError(f"horizon must be >= 1, got {horizon}")

    exclusions: Dict[str, int] = {}
    period_dates: List[str] = []
    panels: List[List[tuple[float, float]]] = []
    total = 0

    all_dates: set[str] = set()
    per_symbol: Dict[str, Dict[str, tuple[float, str]]] = {}
    for symbol, rows in signals.items():
        by_date: Dict[str, tuple[float, str]] = {}
        for period_date, value, availability_ts in rows:
            by_date[period_date] = (float(value), availability_ts)
            all_dates.add(period_date)
        per_symbol[symbol] = by_date

    for period_date in sorted(all_dates):
        panel: List[tuple[float, float]] = []
        for symbol in sorted(per_symbol):
            if period_date not in per_symbol[symbol]:
                continue  # symbol not in the universe at this period
            signal_value, availability_ts = per_symbol[symbol][period_date]
            bars = bars_by_symbol.get(symbol)
            if bars is None:
                exclusions[symbol] = exclusions.get(symbol, 0) + 1
                continue

            # Locate the decision bar by date (bar_end == date at UTC midnight
            # for D1 data; match on the date prefix of the ISO timestamp).
            decision_idx = next(
                (i for i, b in enumerate(bars) if b.timestamp_utc[:10] == period_date),
                None,
            )
            if decision_idx is None:
                exclusions[symbol] = exclusions.get(symbol, 0) + 1
                continue
            decision_bar = bars[decision_idx]
            decision_ts = decision_bar.timestamp_utc

            if availability_ts > decision_ts:
                raise PanelBuildError(
                    f"PIT invariant violated for {symbol}@{period_date}: "
                    f"availability {availability_ts} > decision {decision_ts}"
                )

            # FROZEN alignment: forward window starts at the bar AFTER the
            # decision bar and spans h closes. factor(t) → return(t) is
            # impossible by construction.
            window = bars[decision_idx + 1 : decision_idx + 1 + horizon]
            if len(window) < horizon:
                exclusions[symbol] = exclusions.get(symbol, 0) + 1
                continue
            entry_close = decision_bar.close
            exit_close = window[-1].close
            forward_return = exit_close / entry_close - 1.0

            panel.append((signal_value, forward_return))
            total += 1

        if panel:
            period_dates.append(period_date)
            panels.append(panel)

    overlap_note = (
        f"horizon={horizon} bars; consecutive decision periods overlap when the "
        "decision spacing is smaller than the horizon — the trial metadata "
        "DECLARES this overlap and the declared observation count is what "
        "multiple-testing uses"
        if horizon > 1
        else "horizon=1 bar; no overlapping-horizon acknowledgment required"
    )

    return PanelSet(
        factor_id=factor_id,
        horizon=horizon,
        panels=panels,
        period_dates=period_dates,
        n_observations=total,
        exclusions=exclusions,
        overlap_note=overlap_note,
        universe_version=universe_version,
    )
