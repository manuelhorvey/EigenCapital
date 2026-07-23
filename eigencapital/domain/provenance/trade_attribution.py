"""TradeAttribution — immutable layer-attribution record at trade finalization.

Captures the marginal contribution of each decision lifecycle layer to a
trade's realized outcome. Designed as a **deterministic post-trade compiler**,
not a live subsystem. Written once at trade close, never mutated.

Six attribution layers:

    1. entry_alpha_r      — model signal correctness before lifecycle mgmt
    2. calibration_alpha_r — calibrated vs raw probability decision
    3. exit_alpha_r        — adaptive lifecycle vs static TP/SL
    4. profit_floor_alpha_r — profit floor protection vs unprotected
    5. portfolio_alpha_r   — position sizing vs equal risk
    6. risk_alpha_r        — risk controls vs unrestricted

Each layer uses a three-state status:

    APPLIED       — layer was active and contribution was computed
    NOT_TRIGGERED — layer was active but conditions never met
    NOT_AVAILABLE — layer was disabled or no baseline available

Counterfactual references store the raw baseline values so attribution
can be recomputed under future methodology versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AttributionStatus = Literal["APPLIED", "NOT_TRIGGERED", "NOT_AVAILABLE"]

ATTRIBUTION_VERSION = "v1_alpha"


@dataclass(frozen=True)
class TradeAttribution:
    """Immutable layer attribution for a single trade."""

    trade_id: str
    decision_id: str
    lifecycle_version: str
    realized_r: float

    attribution_version: str = ATTRIBUTION_VERSION

    # ── Layer contributions ─────────────────────────────────────────────
    entry_alpha_r: float | None = None
    entry_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    calibration_alpha_r: float | None = None
    calibration_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    exit_alpha_r: float | None = None
    exit_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    profit_floor_alpha_r: float | None = None
    profit_floor_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    portfolio_alpha_r: float | None = None
    portfolio_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    risk_alpha_r: float | None = None
    risk_alpha_status: AttributionStatus = "NOT_AVAILABLE"

    # ── Counterfactual references ───────────────────────────────────────
    # Raw baseline values so attribution can be recomputed with future
    # methodology versions without re-executing the lifecycle.
    static_exit_r: float | None = None
    counterfactual_version_exit: str | None = None

    uncalibrated_signal_r: float | None = None
    counterfactual_version_calibration: str | None = None

    no_profit_floor_r: float | None = None
    counterfactual_version_profit_floor: str | None = None

    # ── Metadata ────────────────────────────────────────────────────────
    holding_period_candles: int = 0
    entry_archetype: str = ""
    exit_reason: str = ""
    asset: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        d = {
            "trade_id": self.trade_id,
            "decision_id": self.decision_id,
            "lifecycle_version": self.lifecycle_version,
            "attribution_version": self.attribution_version,
            "realized_r": self.realized_r,
            "holding_period_candles": self.holding_period_candles,
            "entry_archetype": self.entry_archetype,
            "exit_reason": self.exit_reason,
            "asset": self.asset,
            "created_at": self.created_at,
        }
        for layer in ("entry", "calibration", "exit", "profit_floor", "portfolio", "risk"):
            alpha = getattr(self, f"{layer}_alpha_r", None)
            status = getattr(self, f"{layer}_alpha_status", "NOT_AVAILABLE")
            d[f"{layer}_alpha_r"] = alpha
            d[f"{layer}_alpha_status"] = status
        d["static_exit_r"] = self.static_exit_r
        d["static_exit_version"] = self.counterfactual_version_exit
        d["uncalibrated_signal_r"] = self.uncalibrated_signal_r
        d["uncalibrated_signal_version"] = self.counterfactual_version_calibration
        d["no_profit_floor_r"] = self.no_profit_floor_r
        d["no_profit_floor_version"] = self.counterfactual_version_profit_floor
        return d
