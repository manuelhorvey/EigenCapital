"""DEPRECATED — legacy position sizing function.

This module is no longer used in live trading.  Position sizing flows through
``paper_trading/entry/`` (``EntryService``, ``EntryOptimizer``) and the
``run_decision_pipeline`` sizing chain (Kelly multiplier, drawdown taper,
position cap, risk cap).

Kept for backward compatibility with existing tests and scripts.
Will be removed in a future release.
"""

import warnings

import pandas as pd

warnings.warn(
    "risk.position_sizing is deprecated and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)


def calculate_position_size(
    signal_df: pd.DataFrame, base_risk: float = 0.01, account_value: float = 100000
) -> pd.Series:
    """
    Calculates position sizes based on signals and regime multipliers.

    .. deprecated::
        Use ``paper_trading.entry.EntryService`` instead.
    """
    return signal_df["signal"] * signal_df["risk_multiplier"]
