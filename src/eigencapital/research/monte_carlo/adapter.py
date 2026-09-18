"""BacktestResults → TradeStream adapter.

R1 Phase A (docs/research/R0_INFRASTRUCTURE_VERIFICATION.md, PATCH item).

Bridges the transient fill evidence of the event-driven backtest engine to the
persisted trade-stream schema. The adapter is deliberately conservative:

- It derives closed round-trips by pairing fills in strict BUY-before-SELL
  (LONG) or SELL-before-BUY (SHORT) alternation. An unmatched trailing fill
  (an open position at backtest end) is rejected — Monte Carlo input must be
  closed trades only. We do not silently drop evidence.
- It does NOT re-derive per-trade P&L from prices. The engine's fill records
  carry commission and fees but not per-trade realized P&L, so per-trade
  realized_pnl must be supplied by the caller (e.g. from the accounting
  ledger). This keeps the adapter honest: no silent recomputation, no
  ambiguity about which P&L definition produced the stream.

The engine's ``trade_count`` is explicitly approximate (``len(fill_events) //
2``); this adapter exists to replace that approximation with a real, verified
trade population.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from eigencapital.research.monte_carlo.schema import (
    TradeRecord,
    TradeStream,
    TradeStreamError,
)


def _opening_side(fill_index: int, side: str) -> str:
    """Map an opening fill side to its position side."""
    if side == "BUY":
        return "LONG"
    if side == "SELL":
        return "SHORT"
    raise TradeStreamError(f"fill {fill_index}: unknown side {side!r}")


def _expected_open_side(position_side: str) -> str:
    """The fill side that OPENS a round-trip of the given position side."""
    return "BUY" if position_side == "LONG" else "SELL"


def backtest_results_to_trade_stream(
    fill_events: Sequence[Dict[str, Any]],
    per_trade_pnl: Sequence[float],
    *,
    stream_id: str,
    experiment_id: str,
    strategy_id: str,
    strategy_version: str,
    dataset_id: str,
    dataset_version: str,
    git_commit: str = "",
    cost_model_id: str = "",
    cost_model_version: str = "",
    instrument: str = "",
    per_trade_costs: Sequence[float] | None = None,
    per_trade_metadata: Sequence[Dict[str, Any]] | None = None,
) -> TradeStream:
    """Build a TradeStream from backtest fill events and per-trade P&L.

    Args:
        fill_events: ``BacktestResults.fill_events`` — dicts with keys
            timestamp, side ("BUY"/"SELL"), quantity, fill_price, commission,
            fees. Must alternate open/close with no partial or overlapping
            positions.
        per_trade_pnl: Realized P&L per closed round-trip, net of costs, in
            trade order. Length must equal the number of paired round-trips.
        stream_id..cost_model_version: Identity fields copied verbatim into
            the stream provenance.
        instrument: Instrument label stamped on every trade.
        per_trade_costs: Optional explicit per-trade total costs. Defaults to
            the sum of the paired fills' commission + fees.
        per_trade_metadata: Optional per-trade metadata dicts.

    Returns:
        A verified TradeStream ready for persistence.

    Raises:
        TradeStreamError: On non-alternating fills, unmatched trailing fills,
            length mismatches, or schema violations.
    """
    fills = list(fill_events)
    pnls = [float(p) for p in per_trade_pnl]
    costs = [float(c) for c in per_trade_costs] if per_trade_costs is not None else None
    metadata = list(per_trade_metadata) if per_trade_metadata is not None else None

    if len(fills) % 2 != 0:
        raise TradeStreamError(
            f"fill_events has odd length ({len(fills)}): an unmatched fill implies an unclosed position"
        )
    if len(pnls) != len(fills) // 2:
        raise TradeStreamError(
            f"per_trade_pnl length ({len(pnls)}) must equal the number of paired round-trips ({len(fills) // 2})"
        )
    if costs is not None and len(costs) != len(pnls):
        raise TradeStreamError(f"per_trade_costs length ({len(costs)}) must equal per_trade_pnl length ({len(pnls)})")
    if metadata is not None and len(metadata) != len(pnls):
        raise TradeStreamError(
            f"per_trade_metadata length ({len(metadata)}) must equal per_trade_pnl length ({len(pnls)})"
        )

    pairs: List[Dict[str, Any]] = []
    opened_side: str | None = None
    open_index = -1
    for index, fill in enumerate(fills):
        side = str(fill.get("side", ""))
        if opened_side is None:
            opened_side = _opening_side(index, side)
            open_index = index
        elif side == _expected_open_side(opened_side):
            raise TradeStreamError(
                f"fill {index}: {side} while a {opened_side} round-trip is open "
                "(pyramiding/scaling is not supported by the pairing adapter)"
            )
        else:
            if side not in ("BUY", "SELL"):
                raise TradeStreamError(f"fill {index}: unknown side {side!r}")
            pairs.append({"open": fills[open_index], "close": fill, "side": opened_side})
            opened_side = None

    if opened_side is not None:
        raise TradeStreamError(
            f"unmatched trailing fill at index {open_index}: position opened but never closed; "
            "Monte Carlo input must be closed trades only"
        )

    if len(pairs) != len(pnls):
        raise TradeStreamError(f"paired {len(pairs)} round-trips but per_trade_pnl has {len(pnls)} entries")

    resolved_instrument = str(instrument or (fills[0].get("instrument", "") if fills else ""))
    if not resolved_instrument:
        raise TradeStreamError(
            "instrument must be provided (or present on fill events); every TradeRecord requires a non-empty instrument"
        )

    records: List[TradeRecord] = []
    for position, pair in enumerate(pairs, start=1):
        open_fill, close_fill = pair["open"], pair["close"]
        trade_costs = (
            costs[position - 1]
            if costs is not None
            else float(open_fill.get("commission", 0.0))
            + float(open_fill.get("fees", 0.0))
            + float(close_fill.get("commission", 0.0))
            + float(close_fill.get("fees", 0.0))
        )
        trade_metadata = dict(metadata[position - 1]) if metadata is not None else {}
        records.append(
            TradeRecord(
                trade_index=position,
                instrument=resolved_instrument,
                entry_timestamp=str(open_fill["timestamp"]),
                exit_timestamp=str(close_fill["timestamp"]),
                side=pair["side"],
                realized_pnl=pnls[position - 1],
                return_r=None,
                costs_paid=trade_costs,
                metadata=trade_metadata,
            )
        )

    return TradeStream(
        stream_id=stream_id,
        experiment_id=experiment_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        git_commit=git_commit,
        cost_model_id=cost_model_id,
        cost_model_version=cost_model_version,
        trades=tuple(records),
    )
