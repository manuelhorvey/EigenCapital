"""Risk Policy — hard constraints and diagnostic thresholds.

Defines the risk boundaries that EigenRisk enforces.
Hard constraints cause REJECTION; diagnostics cause WARNING.

Usage:
    policy = RiskPolicy(
        max_drawdown_pct=10.0,
        daily_loss_limit=5000,
        max_gross_leverage=2.0,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class RiskPolicy:
    """Risk policy with hard constraints and diagnostic thresholds.

    Hard constraints (violation → REJECTED or REDUCED):
        max_drawdown_pct: Maximum drawdown from peak equity (%)
        daily_loss_limit: Maximum loss in a single day (currency)
        weekly_loss_limit: Maximum loss in a single week (currency)
        max_gross_leverage: Maximum gross exposure as multiple of equity
        max_net_leverage: Maximum net exposure as multiple of equity
        max_position_count: Maximum number of open positions
        min_equity: Minimum equity to continue trading
        max_position_notional: Maximum notional per position
        max_position_risk: Maximum risk per position (% of equity)
        max_strategy_exposure: Maximum exposure per strategy (% of equity)
        max_asset_class_exposure: Maximum exposure per asset class (% of equity)
        max_concentration: Maximum concentration in single instrument (% of equity)
        kill_switch: If True, reject ALL new positions

    Diagnostic thresholds (violation → WARNING):
        warn_drawdown_pct: Drawdown warning level (%)
        warn_daily_loss: Daily loss warning level (currency)
        warn_gross_leverage: Leverage warning level
        warn_concentration: Concentration warning level (% of equity)
    """

    # ─── Hard Constraints ──────────────────────────────────────────────
    max_drawdown_pct: float = 10.0
    daily_loss_limit: float = 5_000.0
    weekly_loss_limit: float = 15_000.0
    max_gross_leverage: float = 2.0
    max_net_leverage: float = 1.5
    max_position_count: int = 10
    min_equity: float = 50_000.0
    max_position_notional: float = 500_000.0
    max_position_risk_pct: float = 20.0
    max_strategy_exposure_pct: float = 30.0
    max_asset_class_exposure_pct: float = 40.0
    max_concentration_pct: float = 25.0
    kill_switch: bool = False

    # ─── Diagnostic Thresholds ─────────────────────────────────────────
    warn_drawdown_pct: float = 5.0
    warn_daily_loss: float = 2_000.0
    warn_gross_leverage: float = 1.5
    warn_concentration_pct: float = 15.0
    warn_asset_class_exposure_pct: float = 25.0

    def __post_init__(self) -> None:
        if self.max_drawdown_pct <= 0:
            raise ValueError(f"max_drawdown_pct must be > 0, got {self.max_drawdown_pct}")
        if self.max_gross_leverage <= 0:
            raise ValueError(f"max_gross_leverage must be > 0, got {self.max_gross_leverage}")
        if self.daily_loss_limit < 0:
            raise ValueError(f"daily_loss_limit must be >= 0, got {self.daily_loss_limit}")
        if self.min_equity < 0:
            raise ValueError(f"min_equity must be >= 0, got {self.min_equity}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {k: v for k, v in sorted(self.__dict__.items()) if not k.startswith("_")}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RiskPolicy:
        """Deserialize from dict."""
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})

    @classmethod
    def from_live_config(cls, live_risk: Any) -> RiskPolicy:
        """Derive an EigenRisk policy from the live risk configuration (A1).

        ``LiveRiskConfig`` (config.live_risk) is the canonical, retail-sized
        source of truth for the live system. EigenRisk's default ``RiskPolicy``
        is a research/backtest profile (institution-sized defaults), so any
        live path that routes through EigenRisk must build its policy from the
        live config instead of silently accepting the research defaults.

        Percent-based fields are scaled from the fraction used by the config
        (0.10 == 10%).
        """
        return cls(
            max_drawdown_pct=live_risk.max_account_drawdown_pct * 100.0,
            daily_loss_limit=live_risk.max_daily_loss,
            max_gross_leverage=2.0,
            max_net_leverage=1.5,
            max_position_count=live_risk.max_concurrent_positions,
            min_equity=live_risk.min_equity,
            max_position_notional=live_risk.max_position_notional,
            max_position_risk_pct=live_risk.max_per_position_loss_pct * 100.0,
            kill_switch=False,
        )


# Pre-defined risk policies
CONSERVATIVE = RiskPolicy(
    max_drawdown_pct=5.0,
    daily_loss_limit=2_000.0,
    max_gross_leverage=1.5,
    max_position_count=5,
    min_equity=75_000.0,
)

MODERATE = RiskPolicy()  # Defaults

AGGRESSIVE = RiskPolicy(
    max_drawdown_pct=15.0,
    daily_loss_limit=10_000.0,
    max_gross_leverage=3.0,
    max_position_count=20,
    min_equity=25_000.0,
)
