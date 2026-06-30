"""Trade Attribution Analytics — Causal Attribution Layer.

Phase 6: Observe everything, mutate nothing.
Never feeds back into labels, frozen kernel, or policies.

Four attribution domains:
  1. Prediction  — Was the forecast directionally correct?
  2. Execution   — Did entry timing improve or degrade expectancy?
  3. Exit        — Did TP geometry preserve convexity?
  4. Friction    — How much edge died from fills / slippage / delay?

Counterfactual metrics compare what happened vs alternatives.
MAE/MFE are time-normalized to avoid hold-time bias.
Archetype drift tracks entry->exit structural mutation.
Version hashes preserve full replayability.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, fields
from datetime import datetime

from paper_trading.entry.decision import PositionSide

logger = logging.getLogger("quorrin.trade_attribution")


# ── Four Attribution Domains ──────────────────────────────────────


@dataclass
class PredictionAttribution:
    """Layer 1: Was the forecast directionally correct?

    Captures model intent and confidence at entry.
    `forecast_direction_correct` is set at trade exit.
    """

    signal: str  # BUY / SELL
    label: int
    confidence: float
    prob_long: float
    prob_short: float
    prob_neutral: float
    meta_proba: float | None
    forecast_direction_correct: bool | None = None  # resolved at exit
    regime_at_entry: str = ""
    archetype_at_entry: str = ""
    label_version: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class ExecutionAttribution:
    """Layer 2: Did entry timing improve or degrade expectancy?

    Compares actual fill to signal-time mid.
    Captures deferred entry cost/benefit.
    """

    entry_type: str  # immediate, deferred
    deferred_bars: int
    entry_price: float
    mid_price_at_signal: float
    entry_slippage_bps: float
    spread_at_entry_bps: float | None = None
    entry_pressure_pct: float | None = None
    entry_volatility_rank: float | None = None
    counterfactual_entry_timing_r: float | None = None  # set at exit

    @property
    def entry_timing_efficiency(self) -> float | None:
        if self.entry_price <= 0 or self.mid_price_at_signal <= 0:
            return None
        return self.entry_price / self.mid_price_at_signal

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class ExitAttribution:
    """Layer 3: Did TP geometry preserve convexity?

    MAE/MFE are time-normalised per bar.
    `exit_archetype` captures structural drift from entry.
    """

    exit_reason: str  # SL, TP, BREAKEVEN, EXPIRY, FLIP, MANUAL
    realized_r: float
    theoretical_r: float
    mae: float  # max adverse excursion (in price)
    mfe: float  # max favorable excursion (in price)
    mae_per_bar: float
    mfe_per_bar: float
    time_to_max_adverse: int  # bars from entry
    time_to_max_favorable: int  # bars from entry
    bars_held: int
    counterfactual_fixed_tp_r: float | None = None
    counterfactual_convex_tp_r: float | None = None
    exit_archetype: str = ""
    meta_bucket: str = ""  # "0.50-0.60", "0.60-0.70", ..., "0.90-1.00", "none"

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class FrictionAttribution:
    """Layer 4: How much edge died from fills / slippage / delay?

    Counterfactuals compare ideal (zero-friction) vs real fills.
    """

    entry_slippage_bps: float
    exit_slippage_bps: float
    gap_fill: bool
    partial_fill: bool
    fill_qty_ratio: float
    latency_bars: int
    counterfactual_ideal_fill_r: float | None = None
    counterfactual_real_fill_r: float | None = None
    fill_model_version: str = ""
    execution_model_version: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ── Decision Quality (outcome-independent) ─────────────────────────


@dataclass
class DecisionQuality:
    """Measures decision quality independent of outcome.

    A good decision can lose. A bad decision can win.
    These metrics capture the decision's structural merit.
    """

    entry_pressure_pct: float | None
    spread_rank: float | None
    volatility_rank: float | None
    liquidity_rank: float | None
    entry_distance_from_structure: float | None

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ── Aggregated Record ──────────────────────────────────────────────


@dataclass
class TradeAttributionRecord:
    """Complete attribution record for one trade.

    Contains all four attribution layers plus metadata for
    replayability and cross-trade analytics.
    This is a passive observation — never mutates system state.
    """

    trade_id: str
    asset: str
    entry_date: str
    exit_date: str
    side: str
    policy_hash: str
    archetype_version: str
    execution_model_version: str
    fill_model_version: str
    prediction: PredictionAttribution
    execution: ExecutionAttribution
    exit_info: ExitAttribution | None
    friction: FrictionAttribution
    decision_quality: DecisionQuality
    entry_price: float
    exit_price: float
    realized_return: float
    realized_pnl: float
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Flatten to a single-level dict suitable for DataFrame rows."""
        d: dict = {}
        d["trade_id"] = self.trade_id
        d["asset"] = self.asset
        d["entry_date"] = self.entry_date
        d["exit_date"] = self.exit_date
        d["side"] = self.side
        d["policy_hash"] = self.policy_hash
        d["archetype_version"] = self.archetype_version
        d["execution_model_version"] = self.execution_model_version
        d["fill_model_version"] = self.fill_model_version
        d["entry_price"] = self.entry_price
        d["exit_price"] = self.exit_price
        d["realized_return"] = self.realized_return
        d["realized_pnl"] = self.realized_pnl
        d["created_at"] = self.created_at
        d["experiment_id"] = ""
        # prediction domain
        d.update({f"pred_{k}": v for k, v in self.prediction.to_dict().items()})
        # execution domain
        d.update({f"exec_{k}": v for k, v in self.execution.to_dict().items()})
        # exit domain
        if self.exit_info is not None:
            d.update({f"exit_{k}": v for k, v in self.exit_info.to_dict().items()})
        else:
            d.update({f"exit_{f.name}": None for f in fields(ExitAttribution)})
        # friction domain
        d.update({f"friction_{k}": v for k, v in self.friction.to_dict().items()})
        # decision quality
        d.update({f"dq_{k}": v for k, v in self.decision_quality.to_dict().items()})
        return d

    @classmethod
    def to_frame(cls, records: list[TradeAttributionRecord], experiment_id: str = "") -> pd.DataFrame:  # noqa: F821
        """Build a DataFrame from a list of records."""
        import pandas as pd  # noqa: F401  # defer import

        rows = [r.to_dict() for r in records]
        for row in rows:
            row["experiment_id"] = experiment_id
        return pd.DataFrame.from_records(rows) if rows else pd.DataFrame()


# ── Counterfactual Helpers ─────────────────────────────────────────


def compute_mae_mfe(
    entry_price: float,
    side: str,
    high_prices: list[float],
    low_prices: list[float],
) -> tuple[float, float, int, int]:
    """Compute MAE / MFE and time-to-extreme from bar-level prices.

    Returns (mae, mfe, time_to_max_adverse, time_to_max_favorable)
    where times are bar indices (0 = entry bar).
    """
    if not high_prices or not low_prices or entry_price <= 0:
        return 0.0, 0.0, 0, 0

    if side in ("long", PositionSide.LONG):
        favorable = [max(0.0, h - entry_price) for h in high_prices]
        adverse = [max(0.0, entry_price - low) for low in low_prices]
    else:
        favorable = [max(0.0, entry_price - low) for low in low_prices]
        adverse = [max(0.0, h - entry_price) for h in high_prices]

    mfe = max(favorable) if favorable else 0.0
    mae = max(adverse) if adverse else 0.0
    time_to_mfe = favorable.index(mfe) if mfe > 0 and favorable else 0
    time_to_mae = adverse.index(mae) if mae > 0 and adverse else 0
    return mae, mfe, time_to_mae, time_to_mfe


# ── Collector ──────────────────────────────────────────────────────


class AttributionCollector:
    """Passive observer of trade lifecycle.

    Collects attribution data across entry, exit, and fill events.
    Computes counterfactuals and MAE/MFE at close time.
    Never mutates labels, kernel, policies, or trade outcomes.
    """

    def __init__(self):
        self._records: dict[str, TradeAttributionRecord] = {}
        self._trade_high: dict[str, list[float]] = {}
        self._trade_low: dict[str, list[float]] = {}
        self._trade_high_ts: dict[str, list[int]] = {}
        self._trade_low_ts: dict[str, list[int]] = {}
        self._next_records: dict[str, dict] = {}  # partial data until close

    def record_prediction(
        self,
        trade_id: str,
        signal: str,
        label: int,
        confidence: float,
        prob_long: float,
        prob_short: float,
        prob_neutral: float,
        meta_proba: float | None = None,
        regime_at_entry: str = "",
        archetype_at_entry: str = "",
        label_version: str = "",
    ) -> None:
        self._ensure_scratch(trade_id)
        self._next_records[trade_id]["prediction"] = PredictionAttribution(
            signal=signal,
            label=label,
            confidence=confidence,
            prob_long=prob_long,
            prob_short=prob_short,
            prob_neutral=prob_neutral,
            meta_proba=meta_proba,
            regime_at_entry=regime_at_entry,
            archetype_at_entry=archetype_at_entry,
            label_version=label_version,
        )

    def record_execution(
        self,
        trade_id: str,
        entry_type: str,
        deferred_bars: int,
        entry_price: float,
        mid_price_at_signal: float,
        entry_slippage_bps: float,
        spread_at_entry_bps: float | None = None,
        entry_pressure_pct: float | None = None,
        entry_volatility_rank: float | None = None,
    ) -> None:
        self._ensure_scratch(trade_id)
        self._next_records[trade_id]["execution"] = ExecutionAttribution(
            entry_type=entry_type,
            deferred_bars=deferred_bars,
            entry_price=entry_price,
            mid_price_at_signal=mid_price_at_signal,
            entry_slippage_bps=entry_slippage_bps,
            spread_at_entry_bps=spread_at_entry_bps,
            entry_pressure_pct=entry_pressure_pct,
            entry_volatility_rank=entry_volatility_rank,
        )

    def record_friction(
        self,
        trade_id: str,
        entry_slippage_bps: float,
        exit_slippage_bps: float,
        gap_fill: bool = False,
        partial_fill: bool = False,
        fill_qty_ratio: float = 1.0,
        latency_bars: int = 0,
        fill_model_version: str = "",
        execution_model_version: str = "",
    ) -> None:
        self._ensure_scratch(trade_id)
        self._next_records[trade_id]["friction"] = FrictionAttribution(
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=exit_slippage_bps,
            gap_fill=gap_fill,
            partial_fill=partial_fill,
            fill_qty_ratio=fill_qty_ratio,
            latency_bars=latency_bars,
            fill_model_version=fill_model_version,
            execution_model_version=execution_model_version,
        )

    def record_decision_quality(
        self,
        trade_id: str,
        entry_pressure_pct: float | None = None,
        spread_rank: float | None = None,
        volatility_rank: float | None = None,
        liquidity_rank: float | None = None,
        entry_distance_from_structure: float | None = None,
    ) -> None:
        self._ensure_scratch(trade_id)
        self._next_records[trade_id]["decision_quality"] = DecisionQuality(
            entry_pressure_pct=entry_pressure_pct,
            spread_rank=spread_rank,
            volatility_rank=volatility_rank,
            liquidity_rank=liquidity_rank,
            entry_distance_from_structure=entry_distance_from_structure,
        )

    def update_trade_extremes(
        self,
        trade_id: str,
        high: float,
        low: float,
        bar_index: int,
    ) -> None:
        """Track high/low prices during the trade for MAE/MFE computation."""
        if trade_id not in self._trade_high:
            self._trade_high[trade_id] = []
            self._trade_low[trade_id] = []
            self._trade_high_ts[trade_id] = []
            self._trade_low_ts[trade_id] = []
        if high > 0:
            self._trade_high[trade_id].append(high)
            self._trade_high_ts[trade_id].append(bar_index)
        if low > 0:
            self._trade_low[trade_id].append(low)
            self._trade_low_ts[trade_id].append(bar_index)

    def finalize(
        self,
        trade_id: str,
        asset: str,
        entry_date: str,
        exit_date: str,
        side: str,
        exit_price: float,
        exit_reason: str,
        realized_r: float,
        realized_return: float,
        realized_pnl: float,
        theoretical_r: float,
        policy_hash: str = "",
        archetype_version: str = "",
        exit_archetype: str = "",
        counterfactual_fixed_tp_r: float | None = None,
        counterfactual_convex_tp_r: float | None = None,
        counterfactual_ideal_fill_r: float | None = None,
        counterfactual_real_fill_r: float | None = None,
        counterfactual_entry_timing_r: float | None = None,
    ) -> TradeAttributionRecord | None:
        """Finalize and store the attribution record at trade close.

        Computes MAE/MFE from tracked extremes, then assembles
        the full TradeAttributionRecord. Returns None if the
        trade_id was never initialised via record_prediction.
        """
        scratch = self._next_records.get(trade_id)
        if scratch is None:
            logger.warning("trade_attribution: no scratch for trade_id=%s", trade_id)
            return None

        pred: PredictionAttribution = scratch.get("prediction")
        exec_attr: ExecutionAttribution = scratch.get("execution")
        friction: FrictionAttribution = scratch.get("friction")
        dq: DecisionQuality = scratch.get("decision_quality")

        if pred is None:
            logger.warning("trade_attribution: no prediction for trade_id=%s", trade_id)
            return None

        # Resolve forecast direction at exit
        if exit_reason != "FLIP":
            price_moved_up = exit_price > exec_attr.entry_price if exec_attr else False
            if side == "long":
                pred.forecast_direction_correct = price_moved_up
            else:
                pred.forecast_direction_correct = not price_moved_up

        # Compute MAE / MFE
        high_prices = self._trade_high.pop(trade_id, [])
        low_prices = self._trade_low.pop(trade_id, [])

        entry_price = exec_attr.entry_price if exec_attr else 0.0
        mae, mfe, time_to_mae, time_to_mfe = compute_mae_mfe(entry_price, side, high_prices, low_prices)

        bars_held_attr = 0
        try:
            bars_held_attr = max(
                0,
                (datetime.fromisoformat(exit_date) - datetime.fromisoformat(entry_date)).days,
            )
        except (ValueError, TypeError):
            bars_held_attr = 0
        bars_held_attr = max(bars_held_attr, 1)

        # Compute meta-confidence bucket for stratification
        meta_proba = pred.meta_proba
        if meta_proba is None:
            meta_bucket = "none"
        elif meta_proba < 0.50:
            meta_bucket = "0.00-0.50"
        elif meta_proba < 0.60:
            meta_bucket = "0.50-0.60"
        elif meta_proba < 0.70:
            meta_bucket = "0.60-0.70"
        elif meta_proba < 0.80:
            meta_bucket = "0.70-0.80"
        elif meta_proba < 0.90:
            meta_bucket = "0.80-0.90"
        else:
            meta_bucket = "0.90-1.00"

        exit_attr = ExitAttribution(
            exit_reason=exit_reason,
            realized_r=realized_r,
            theoretical_r=theoretical_r,
            mae=mae,
            mfe=mfe,
            mae_per_bar=round(mae / bars_held_attr, 6),
            mfe_per_bar=round(mfe / bars_held_attr, 6),
            time_to_max_adverse=time_to_mae,
            time_to_max_favorable=time_to_mfe,
            bars_held=bars_held_attr,
            counterfactual_fixed_tp_r=counterfactual_fixed_tp_r,
            counterfactual_convex_tp_r=counterfactual_convex_tp_r,
            exit_archetype=exit_archetype or pred.archetype_at_entry,
            meta_bucket=meta_bucket,
        )

        # Build execution counterfactual
        if exec_attr and counterfactual_entry_timing_r is not None:
            exec_attr.counterfactual_entry_timing_r = counterfactual_entry_timing_r

        # Build friction counterfactual
        if counterfactual_ideal_fill_r is not None and counterfactual_real_fill_r is not None:
            friction.counterfactual_ideal_fill_r = counterfactual_ideal_fill_r
            friction.counterfactual_real_fill_r = counterfactual_real_fill_r

        if exec_attr is None:
            exec_attr = ExecutionAttribution(
                entry_type="unknown",
                deferred_bars=0,
                entry_price=0.0,
                mid_price_at_signal=0.0,
                entry_slippage_bps=0.0,
            )
        if friction is None:
            friction = FrictionAttribution(
                entry_slippage_bps=0.0,
                exit_slippage_bps=0.0,
                gap_fill=False,
                partial_fill=False,
                fill_qty_ratio=1.0,
                latency_bars=0,
            )
        if dq is None:
            dq = DecisionQuality(None, None, None, None, None)

        record = TradeAttributionRecord(
            trade_id=trade_id,
            asset=asset,
            entry_date=entry_date,
            exit_date=exit_date,
            side=side,
            policy_hash=policy_hash,
            archetype_version=archetype_version,
            execution_model_version=friction.execution_model_version,
            fill_model_version=friction.fill_model_version,
            prediction=pred,
            execution=exec_attr,
            exit_info=exit_attr,
            friction=friction,
            decision_quality=dq,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_return=realized_return,
            realized_pnl=realized_pnl,
        )
        self._records[trade_id] = record
        del self._next_records[trade_id]
        logger.debug("trade_attribution: finalized trade_id=%s (r=%.2f)", trade_id, realized_r)
        return record

    def get_record(self, trade_id: str) -> TradeAttributionRecord | None:
        return self._records.get(trade_id)

    def get_all(self) -> list[TradeAttributionRecord]:
        return list(self._records.values())

    def count(self) -> int:
        return len(self._records)

    def flush_to(self, records: list[TradeAttributionRecord]) -> None:
        """Merge collected records into an external list (e.g. state_store)."""
        records.extend(self._records.values())
        self._records.clear()

    def _ensure_scratch(self, trade_id: str) -> None:
        if trade_id not in self._next_records:
            self._next_records[trade_id] = {}
            self._trade_high[trade_id] = []
            self._trade_low[trade_id] = []
            self._trade_high_ts[trade_id] = []
            self._trade_low_ts[trade_id] = []

    def reset(self) -> None:
        """Clear all records for test isolation."""
        self._records.clear()
        self._next_records.clear()
        self._trade_high.clear()
        self._trade_low.clear()
        self._trade_high_ts.clear()
        self._trade_low_ts.clear()


# ── Utility ────────────────────────────────────────────────────────


def hash_policy_state(policy_hash: str = "", archetype_version: str = "") -> str:
    raw = f"{policy_hash}:{archetype_version}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]
