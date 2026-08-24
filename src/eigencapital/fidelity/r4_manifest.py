"""R4 Config Manifest — frozen configuration identity for the R4 paper fidelity campaign.

Every parameter is frozen before the campaign runs.
Any change invalidates the campaign and requires a new one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class R4ConfigManifest:
    """Immutable frozen R4 configuration.

    This manifest captures the EXACT configuration that produced the
    SUPPORTED verdict in Campaign R4. The paper fidelity campaign must
    reproduce this configuration exactly.
    """

    # Strategy identity
    strategy_name: str = "risk_conditioned_continuation"
    strategy_version: str = "R4.0"
    strategy_hash: str = ""

    # Feature registry
    feature_registry_version: str = "1.0"
    feature_registry_hash: str = ""

    # Data snapshot
    data_source: str = "exness_mt5"
    data_terminal_id: str = "168966110"
    data_snapshot_hash: str = ""
    data_start_date: str = "2020-01-01"
    data_end_date: str = "2026-08-24"
    data_bar_count: int = 31790

    # Universe
    universe: Dict[str, str] = field(default_factory=lambda: {
        "EURUSDm": "forex",
        "GBPUSDm": "forex",
        "USDJPYm": "forex",
        "AUDUSDm": "forex",
        "USDCADm": "forex",
        "USDCHFm": "forex",
        "NZDUSDm": "forex",
        "XAUUSDm": "metals",
        "XAGUSDm": "metals",
        "US500m": "indices",
        "US30m": "indices",
        "USTECm": "indices",
        "BTCUSDm": "crypto",
        "ETHUSDm": "crypto",
        "USOILm": "energy",
    })

    # Risk parameters (R4 pre-registered)
    crypto_max_allocation: float = 0.10       # 10% max crypto
    asset_risk_limit: float = 0.02            # 2% max risk per asset
    correlation_threshold: float = 0.7        # reduce weight above this
    drawdown_control_threshold: float = -0.15 # reduce exposure after -15% DD
    drawdown_control_reduction: float = 0.50  # reduce by 50%
    regime_vol_lookback: int = 20             # days for regime detection
    regime_high_vol_threshold: float = 0.75   # 75th percentile = high vol

    # Volatility targeting
    vol_target_annual: float = 0.10           # 10% target vol
    vol_lookback: int = 20                    # days for vol estimation

    # Risk parity
    risk_parity_method: str = "equal_risk_contribution"
    risk_parity_rebalance: int = 21           # monthly

    # Signal parameters
    signal_lookback_short: int = 63           # 3 months
    signal_lookback_long: int = 252           # 12 months
    signal_combination: str = "risk_conditioned"

    # Execution assumptions
    transaction_cost_bps: float = 10.0        # 10 bps per trade
    slippage_bps: float = 5.0                 # 5 bps slippage
    rebalance_frequency: str = "weekly"

    # Cost model
    cost_model_version: str = "R4.0"
    cost_model_hash: str = ""

    # Validation
    walk_forward_folds: int = 5
    stress_max_dd_threshold: float = -0.25    # -25% max stress DD
    min_sharpe_threshold: float = 0.5

    def compute_identity(self) -> str:
        """Compute deterministic fingerprint of the entire R4 config."""
        data = {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "strategy_hash": self.strategy_hash,
            "feature_registry_version": self.feature_registry_version,
            "feature_registry_hash": self.feature_registry_hash,
            "data_snapshot_hash": self.data_snapshot_hash,
            "data_start_date": self.data_start_date,
            "data_end_date": self.data_end_date,
            "universe": dict(sorted(self.universe.items())),
            "crypto_max_allocation": self.crypto_max_allocation,
            "asset_risk_limit": self.asset_risk_limit,
            "correlation_threshold": self.correlation_threshold,
            "drawdown_control_threshold": self.drawdown_control_threshold,
            "drawdown_control_reduction": self.drawdown_control_reduction,
            "regime_vol_lookback": self.regime_vol_lookback,
            "regime_high_vol_threshold": self.regime_high_vol_threshold,
            "vol_target_annual": self.vol_target_annual,
            "vol_lookback": self.vol_lookback,
            "risk_parity_method": self.risk_parity_method,
            "risk_parity_rebalance": self.risk_parity_rebalance,
            "signal_lookback_short": self.signal_lookback_short,
            "signal_lookback_long": self.signal_lookback_long,
            "signal_combination": self.signal_combination,
            "transaction_cost_bps": self.transaction_cost_bps,
            "slippage_bps": self.slippage_bps,
            "rebalance_frequency": self.rebalance_frequency,
            "cost_model_version": self.cost_model_version,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "strategy_hash": self.strategy_hash,
            "feature_registry_version": self.feature_registry_version,
            "feature_registry_hash": self.feature_registry_hash,
            "data_source": self.data_source,
            "data_terminal_id": self.data_terminal_id,
            "data_snapshot_hash": self.data_snapshot_hash,
            "data_start_date": self.data_start_date,
            "data_end_date": self.data_end_date,
            "data_bar_count": self.data_bar_count,
            "universe": dict(sorted(self.universe.items())),
            "crypto_max_allocation": self.crypto_max_allocation,
            "asset_risk_limit": self.asset_risk_limit,
            "correlation_threshold": self.correlation_threshold,
            "drawdown_control_threshold": self.drawdown_control_threshold,
            "drawdown_control_reduction": self.drawdown_control_reduction,
            "regime_vol_lookback": self.regime_vol_lookback,
            "regime_high_vol_threshold": self.regime_high_vol_threshold,
            "vol_target_annual": self.vol_target_annual,
            "vol_lookback": self.vol_lookback,
            "risk_parity_method": self.risk_parity_method,
            "risk_parity_rebalance": self.risk_parity_rebalance,
            "signal_lookback_short": self.signal_lookback_short,
            "signal_lookback_long": self.signal_lookback_long,
            "signal_combination": self.signal_combination,
            "transaction_cost_bps": self.transaction_cost_bps,
            "slippage_bps": self.slippage_bps,
            "rebalance_frequency": self.rebalance_frequency,
            "cost_model_version": self.cost_model_version,
            "walk_forward_folds": self.walk_forward_folds,
            "stress_max_dd_threshold": self.stress_max_dd_threshold,
            "min_sharpe_threshold": self.min_sharpe_threshold,
            "manifest_identity": self.compute_identity(),
        }
