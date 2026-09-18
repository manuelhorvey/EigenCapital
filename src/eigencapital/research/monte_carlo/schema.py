"""Trade Stream Schema — persisted per-trade identity for Monte Carlo research.

R1 Phase A (docs/research/R0_INFRASTRUCTURE_VERIFICATION.md, PATCH item): the
single input dependency of the Monte Carlo diagnostic framework is a
deterministic, provenance-stamped sequence of closed trades. Historically that
evidence lived only transiently in ``BacktestResults.fill_events`` and
qualification datasets; this module defines the persistent schema so Monte
Carlo reshuffling, bootstrap and block bootstrap consume *the same trade
population* the historical statistics were computed from.

Invariants enforced here:
- Trade indices are contiguous and 1-based, in order (deterministic ordering).
- Exit timestamps are monotonic non-decreasing across the stream.
- Every trade is closed: entry_timestamp <= exit_timestamp.
- P&L and cost values are finite; costs are non-negative.
- The provenance hash is a SHA-256 over the canonical JSON of the full stream
  (identity fields + every trade record), computed via
  ``eigencapital.core.provenance.compute_provenance_hash``.

Scope guard (frozen review §14): research-only. Never touches R4, the risk
engine, or execution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from eigencapital.core.provenance import compute_provenance_hash

TRADE_STREAM_SCHEMA_VERSION = "1"

_SIDES = ("LONG", "SHORT")


class TradeStreamError(ValueError):
    """Raised on invalid trade-stream construction, parsing, or verification."""

    def __init__(self, message: str, stream_id: str = "") -> None:
        super().__init__(message)
        self.stream_id = stream_id


def _require_iso8601(value: str, name: str) -> None:
    if not value or "T" not in value:
        raise TradeStreamError(f"{name} must be a non-empty ISO-8601 timestamp, got: {value!r}")


def _require_finite(value: float, name: str) -> float:
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise TradeStreamError(f"{name} must be numeric, got: {value!r}") from exc
    if not math.isfinite(as_float):
        raise TradeStreamError(f"{name} must be finite, got: {value!r}")
    return as_float


@dataclass(frozen=True)
class TradeRecord:
    """One closed trade with full identity.

    Attributes:
        trade_index: 1-based contiguous position within the stream.
        instrument: Instrument/symbol identifier (non-empty).
        entry_timestamp: ISO-8601 timestamp of the entry fill.
        exit_timestamp: ISO-8601 timestamp of the exit fill (>= entry).
        side: "LONG" or "SHORT".
        realized_pnl: Realized P&L in account currency, net of costs.
        return_r: Optional normalized return (e.g. R-multiple or
            pnl/initial_cash). None when the normalization is not defined.
        costs_paid: Total transaction costs for the round trip (>= 0).
        metadata: Optional extra evidence (e.g. entry/exit ticket ids).
    """

    trade_index: int
    instrument: str
    entry_timestamp: str
    exit_timestamp: str
    side: str
    realized_pnl: float
    return_r: float | None
    costs_paid: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.trade_index, int) or self.trade_index < 1:
            raise TradeStreamError(f"trade_index must be an int >= 1, got {self.trade_index!r}")
        if not self.instrument:
            raise TradeStreamError("instrument must be non-empty")
        _require_iso8601(self.entry_timestamp, "entry_timestamp")
        _require_iso8601(self.exit_timestamp, "exit_timestamp")
        if self.entry_timestamp > self.exit_timestamp:
            raise TradeStreamError(
                f"entry_timestamp ({self.entry_timestamp}) must be <= exit_timestamp ({self.exit_timestamp})"
            )
        if self.side not in _SIDES:
            raise TradeStreamError(f"side must be one of {_SIDES}, got {self.side!r}")
        object.__setattr__(self, "realized_pnl", _require_finite(self.realized_pnl, "realized_pnl"))
        object.__setattr__(self, "costs_paid", _require_finite(self.costs_paid, "costs_paid"))
        if self.costs_paid < 0:
            raise TradeStreamError(f"costs_paid must be >= 0, got {self.costs_paid!r}")
        if self.return_r is not None:
            object.__setattr__(self, "return_r", _require_finite(self.return_r, "return_r"))
        if not isinstance(self.metadata, dict):
            raise TradeStreamError("metadata must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization (field order as declared)."""
        return {
            "trade_index": self.trade_index,
            "instrument": self.instrument,
            "entry_timestamp": self.entry_timestamp,
            "exit_timestamp": self.exit_timestamp,
            "side": self.side,
            "realized_pnl": self.realized_pnl,
            "return_r": self.return_r,
            "costs_paid": self.costs_paid,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TradeRecord:
        """Strict parse: unknown keys are rejected (provenance integrity)."""
        known = {
            "trade_index",
            "instrument",
            "entry_timestamp",
            "exit_timestamp",
            "side",
            "realized_pnl",
            "return_r",
            "costs_paid",
            "metadata",
        }
        unknown = set(data) - known
        if unknown:
            raise TradeStreamError(f"unknown TradeRecord field(s): {sorted(unknown)}")
        missing = known - set(data)
        if missing:
            raise TradeStreamError(f"missing TradeRecord field(s): {sorted(missing)}")
        return cls(
            trade_index=data["trade_index"],
            instrument=data["instrument"],
            entry_timestamp=data["entry_timestamp"],
            exit_timestamp=data["exit_timestamp"],
            side=data["side"],
            realized_pnl=data["realized_pnl"],
            return_r=data["return_r"],
            costs_paid=data["costs_paid"],
            metadata=dict(data["metadata"]),
        )


@dataclass(frozen=True)
class TradeStream:
    """A persisted, provenance-stamped sequence of closed trades.

    Attributes:
        stream_id: Unique identifier for this stream (e.g. "TS-R4-DAILY-0001").
        experiment_id: Owning experiment (links to the experiment registry).
        strategy_id: Strategy identifier (e.g. "R4").
        strategy_version: Strategy code version.
        dataset_id: Dataset identifier used by the producing backtest.
        dataset_version: Dataset version.
        git_commit: Code state of the producing backtest.
        cost_model_id: Cost model identifier applied by the producing backtest.
        cost_model_version: Cost model version.
        schema_version: Trade-stream schema version.
        trades: Closed trades in deterministic order (contiguous 1..N indices).
        provenance_hash: SHA-256 over identity fields + all trade records.
    """

    stream_id: str
    experiment_id: str
    strategy_id: str
    strategy_version: str
    dataset_id: str
    dataset_version: str
    git_commit: str
    cost_model_id: str
    cost_model_version: str
    trades: Tuple[TradeRecord, ...]
    schema_version: str = TRADE_STREAM_SCHEMA_VERSION
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        for name in (
            "stream_id",
            "experiment_id",
            "strategy_id",
            "dataset_id",
        ):
            if not getattr(self, name):
                raise TradeStreamError(f"{name} must be non-empty")
        if not self.trades:
            raise TradeStreamError("trades must be non-empty (zero-trade streams are not valid MC input)")
        trades = tuple(self.trades)
        object.__setattr__(self, "trades", trades)
        for position, record in enumerate(trades, start=1):
            if record.trade_index != position:
                raise TradeStreamError(
                    f"trade indices must be contiguous 1..N in order; position {position} "
                    f"has trade_index {record.trade_index}"
                )
            if position > 1 and trades[position - 2].exit_timestamp > record.exit_timestamp:
                raise TradeStreamError(
                    f"exit_timestamps must be monotonic non-decreasing; trade {position} "
                    f"({record.exit_timestamp}) precedes trade {position - 1} "
                    f"({trades[position - 2].exit_timestamp})"
                )
        if not self.provenance_hash:
            object.__setattr__(self, "provenance_hash", self.compute_provenance_hash())

    def content_hash_inputs(self) -> Dict[str, Any]:
        """Canonical hash input: identity fields plus every trade record."""
        return {
            "schema": "eigencapital.trade_stream",
            "schema_version": self.schema_version,
            "stream_id": self.stream_id,
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "git_commit": self.git_commit,
            "cost_model_id": self.cost_model_id,
            "cost_model_version": self.cost_model_version,
            "trades": [t.to_dict() for t in self.trades],
        }

    def compute_provenance_hash(self) -> str:
        """Deterministic SHA-256 over the full stream content."""
        return compute_provenance_hash(self.content_hash_inputs())

    def verify_provenance_hash(self, expected_hash: str) -> bool:
        """Verify the stream content matches an expected provenance hash."""
        return self.compute_provenance_hash() == expected_hash

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization including the provenance hash."""
        return {
            "stream_id": self.stream_id,
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "git_commit": self.git_commit,
            "cost_model_id": self.cost_model_id,
            "cost_model_version": self.cost_model_version,
            "schema_version": self.schema_version,
            "trades": [t.to_dict() for t in self.trades],
            "provenance_hash": self.provenance_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TradeStream:
        """Strict parse: unknown keys are rejected (provenance integrity)."""
        known = {
            "stream_id",
            "experiment_id",
            "strategy_id",
            "strategy_version",
            "dataset_id",
            "dataset_version",
            "git_commit",
            "cost_model_id",
            "cost_model_version",
            "schema_version",
            "trades",
            "provenance_hash",
        }
        unknown = set(data) - known
        if unknown:
            raise TradeStreamError(f"unknown TradeStream field(s): {sorted(unknown)}")
        missing = known - set(data)
        if missing:
            raise TradeStreamError(f"missing TradeStream field(s): {sorted(missing)}")
        return cls(
            stream_id=data["stream_id"],
            experiment_id=data["experiment_id"],
            strategy_id=data["strategy_id"],
            strategy_version=data["strategy_version"],
            dataset_id=data["dataset_id"],
            dataset_version=data["dataset_version"],
            git_commit=data["git_commit"],
            cost_model_id=data["cost_model_id"],
            cost_model_version=data["cost_model_version"],
            schema_version=data["schema_version"],
            trades=tuple(TradeRecord.from_dict(t) for t in data["trades"]),
            provenance_hash=data["provenance_hash"],
        )
