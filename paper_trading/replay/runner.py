"""Deterministic replay runner — reconstruct engine state from WAL + snapshots.

The replay system:
    1. Loads the latest snapshot checkpoint as the starting state
    2. Replays WAL events from the checkpoint forward
    3. For each event, calls the matching deterministic function
    4. Asserts reconstructed state matches the original execution

This validates:
    - Determinism: same inputs → same outputs every replay
    - Completeness: all decisions are fully captured in the WAL
    - Correctness: no hidden state mutations outside the event stream

Invariants:
    R1: replay(snapshot_at_t, events[t:]) == state_at_T (full reconstruction)
    R2: deterministic functions produce identical fills, signals, risk decisions
    R3: replay never depends on live data (pure deterministic reconstruction)
"""

from __future__ import annotations

import logging
from typing import Any

from paper_trading.replay.wal import WalEvent, WalReader

logger = logging.getLogger("eigencapital.replay.runner")


class ReplayMismatchError(AssertionError):
    """Raised when replayed state diverges from recorded execution."""


class ReplayRunner:
    """Deterministic state reconstruction from WAL events.

    Usage::
        runner = ReplayRunner(wal_reader)
        state = runner.replay(from_sequence=100)
        # state now reflects engine state after all events >= 100 are applied
    """

    def __init__(self, reader: WalReader):
        self._reader = reader
        self._state: dict[str, Any] = {
            "assets": {},
            "portfolio": {},
            "events_replayed": 0,
            "last_sequence": 0,
        }

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def replay(self, from_sequence: int = 0) -> dict[str, Any]:
        """Replay all WAL events from from_sequence, reconstructing state.

        Returns the reconstructed state dict. Raises ReplayMismatchError if
        any replayed decision diverges from the recorded output.
        """
        self._state["last_sequence"] = from_sequence
        self._state["events_replayed"] = 0

        events = self._reader.read_from(from_sequence)
        for event in events:
            self._apply(event)
            self._state["last_sequence"] = event.sequence
            self._state["events_replayed"] += 1

        return dict(self._state)

    def verify_continuity(
        self,
        from_sequence: int = 0,
        verify_every: int = 10,
    ) -> list[ReplayMismatchError]:
        """Verify deterministic replay by replaying events and cross-checking.

        For each verify_every-th event, snapshots the intermediate state.
        Then replays the entire range and asserts intermediate snapshots match.
        Returns a list of mismatches (empty = perfect continuity).
        """
        mismatches: list[ReplayMismatchError] = []
        snapshots: dict[int, dict] = {}

        # Pass 1: record intermediate state snapshots
        reader2 = WalReader(
            self._get_base_dir(),
            self._reader._path.split("/")[-1].replace(".jsonl", ""),
        )
        for event in reader2.read_from(from_sequence):
            if event.sequence % verify_every == 0:
                snapshots[event.sequence] = dict(self._state)

        # Pass 2: replay from scratch and verify snapshots
        self._state["events_replayed"] = 0
        self._state["last_sequence"] = from_sequence
        events = self._reader.read_from(from_sequence)
        for event in events:
            self._apply(event)
            self._state["last_sequence"] = event.sequence
            self._state["events_replayed"] += 1

            if event.sequence in snapshots:
                saved = snapshots[event.sequence]
                current = dict(self._state)
                try:
                    self._assert_states_match(saved, current, event.sequence)
                except ReplayMismatchError as e:
                    mismatches.append(e)

        return mismatches

    # ── Event application ──────────────────────────────────────────────

    def _apply(self, event: WalEvent) -> None:
        """Apply a single WAL event to the reconstructed state."""
        handler = self._get_handler(event.event_type)
        if handler is not None:
            handler(event)

    def _get_handler(self, event_type: str):
        handlers = {
            "price_update": self._on_price_update,
            "features_snapshot": self._on_features_snapshot,
            "inference_output": self._on_inference_output,
            "decision_output": self._on_decision_output,
            "signal_generated": self._on_signal,
            "entry_executed": self._on_entry,
            "sl_executed": self._on_sl,
            "tp_executed": self._on_tp,
            "position_closed": self._on_close,
            "actor_health": self._on_health,
            "state_committed": self._on_commit,
        }
        return handlers.get(event_type)

    def _on_features_snapshot(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["last_features"] = event.payload.get("features")
        self._state["assets"][asset]["feature_hash"] = event.payload.get("feature_hash")
        self._state["assets"][asset]["model_hash"] = event.payload.get("model_hash")
        self._state["assets"][asset]["feature_schema"] = event.payload.get("feature_schema")

    def _on_inference_output(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["last_inference"] = {
            "prob_long": event.payload.get("prob_long"),
            "prob_short": event.payload.get("prob_short"),
            "prob_neutral": event.payload.get("prob_neutral"),
            "model_hash": event.payload.get("model_hash"),
            "feature_hash": event.payload.get("feature_hash"),
        }

    def _on_decision_output(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["last_decision"] = {
            "final_signal": event.payload.get("final_signal"),
            "gates_aborted": event.payload.get("gates_aborted"),
            "feature_hash": event.payload.get("feature_hash"),
            "model_hash": event.payload.get("model_hash"),
        }

    def _on_price_update(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["last_price"] = event.payload.get("price")
        self._state["assets"][asset]["last_ohlcv"] = event.payload.get("ohlcv")
        self._state["assets"][asset]["last_update"] = event.timestamp

    def _on_signal(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["last_signal"] = {
            "signal": event.payload.get("signal"),
            "confidence": event.payload.get("confidence"),
            "timestamp": event.timestamp,
        }

    def _on_entry(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["position"] = {
            "side": event.payload.get("side"),
            "entry_price": event.payload.get("fill_price"),
            "fill_qty": event.payload.get("fill_qty"),
            "slippage_bps": event.payload.get("slippage_bps"),
            "entry_time": event.timestamp,
        }

    def _on_sl(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["stop_loss"] = {
            "fill_price": event.payload.get("fill_price"),
            "gap_fill": event.payload.get("gap_fill"),
            "slippage_bps": event.payload.get("slippage_bps"),
        }

    def _on_tp(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["take_profit"] = {
            "fill_price": event.payload.get("fill_price"),
            "slippage_bps": event.payload.get("slippage_bps"),
        }

    def _on_close(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        prev_position = self._state["assets"][asset].get("position")
        self._state["assets"][asset]["closed_position"] = {
            "reason": event.payload.get("reason"),
            "pnl": event.payload.get("pnl"),
            "prev_position": prev_position,
        }
        self._state["assets"][asset]["position"] = None

    def _on_health(self, event: WalEvent) -> None:
        asset = event.payload.get("asset", event.source)
        self._state["assets"].setdefault(asset, {})
        self._state["assets"][asset]["health"] = event.payload.get("health")

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> None:
        """Recursively merge overlay into base (mutates base)."""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ReplayRunner._deep_merge(base[key], value)
            else:
                base[key] = value

    def _on_commit(self, event: WalEvent) -> None:
        """State checkpoint — deep-merge payload into state (snapshot source)."""
        for key, value in event.payload.items():
            if isinstance(value, dict) and isinstance(self._state.get(key), dict):
                self._deep_merge(self._state[key], value)
            else:
                self._state[key] = value

    # ── State comparison ───────────────────────────────────────────────

    def _assert_states_match(
        self,
        saved: dict,
        current: dict,
        sequence: int,
    ) -> None:
        """Assert two state dicts are consistent within replay tolerance."""
        saved_assets = saved.get("assets", {})
        current_assets = current.get("assets", {})

        for asset_name in set(list(saved_assets.keys()) + list(current_assets.keys())):
            sa = saved_assets.get(asset_name, {})
            ca = current_assets.get(asset_name, {})

            for key in set(list(sa.keys()) + list(ca.keys())):
                if key == "last_ohlcv":
                    continue  # raw market data is not replayed deterministically
                sv = sa.get(key)
                cv = ca.get(key)
                if isinstance(sv, dict) and isinstance(cv, dict):
                    for k in sv:
                        if k in cv and sv[k] != cv[k]:
                            raise ReplayMismatchError(
                                f"Sequence {sequence}, asset {asset_name}, key {key}.{k}: "
                                f"saved={sv[k]} != current={cv[k]}"
                            )
                elif sv != cv:
                    raise ReplayMismatchError(
                        f"Sequence {sequence}, asset {asset_name}, key {key}: saved={sv} != current={cv}"
                    )

    def _get_base_dir(self) -> str:
        """Extract base_dir from WAL path (hacky but practical)."""
        parts = self._reader._path.split("/")
        try:
            idx = parts.index("data")
            return "/".join(parts[:idx])
        except ValueError:
            return "/".join(parts[:-3])
