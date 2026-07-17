"""Pydantic validation models for ``EngineConfig`` and ``MT5Config``.

These models are **not** replacements for the dataclass-based config types.
They serve as a compositional guard layer inside ``EngineConfig.__post_init__``
to provide better error messages, JSON Schema output, and type-safe boundary
validation — without changing the public API of the config dataclasses.

Usage::

    from configs.pydantic_models import EngineConfigValidation

    try:
        EngineConfigValidation(
            capital=100_000,
            position_size=0.95,
            rebalance="daily",
            retrain_window=5,
            data_source="yfinance",
            portfolio_drawdown_limit=-0.15,
            mt5_bridge_port=9879,
        )
    except pydantic.ValidationError as exc:
        # exc.errors() contains structured error details
        raise ValueError("...") from exc
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class _RebalanceOption(str, Enum):
    """Valid rebalance frequency values."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    NONE = "none"


class _DataSourceOption(str, Enum):
    """Valid data source values."""

    YFINANCE = "yfinance"
    MT5 = "mt5"


class MT5ConfigValidation(BaseModel, frozen=True):
    """Pydantic validation model for MT5 broker configuration.

    Validates the subset of ``MT5Config`` fields that have runtime
    constraints.  Non-constrained fields (``enabled``, ``account``,
    ``password``, ``server``, ``bridge_host``, ``symbol_map_path``)
    are passthrough strings/booleans.
    """

    enabled: bool = False
    account: int = 0
    password: str = ""
    server: str = ""
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 9879
    symbol_map_path: str = ""

    @field_validator("bridge_port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError(f"bridge_port must be in [1, 65535], got {v}")
        return v


class EngineConfigValidation(BaseModel, frozen=True):
    """Pydantic validation model for the top-level engine configuration.

    Validates the constrained fields that ``EngineConfig.__post_init__``
    currently checks with hand-rolled ``if`` statements.  Non-constrained
    fields (``retrain_freq``, ``research_mode``, ``api_token``, ``mode``,
    and all dict/frozenset fields) are not included — they have no runtime
    value-range constraints and are stored passthrough.

    This is a **compositional guard layer**: the model is constructed once
    in ``__post_init__`` and immediately discarded.  It does **not** replace
    the dataclass — every consumer across the codebase continues to receive
    ``EngineConfig`` as before.
    """

    capital: float = Field(default=100_000, gt=0)
    position_size: float = Field(default=0.95, gt=0, le=1.0)
    rebalance: str = Field(default="daily")
    retrain_window: int = Field(default=5, ge=1)
    data_source: str = Field(default="yfinance")
    portfolio_drawdown_limit: float = Field(default=-0.15, ge=-1.0, le=0.0)
    mt5_bridge_port: int = Field(default=9879)

    # ── Field-level validators ────────────────────────────────────────

    @field_validator("rebalance")
    @classmethod
    def _rebalance_value(cls, v: str) -> str:
        try:
            return _RebalanceOption(v).value
        except ValueError:
            allowed = [e.value for e in _RebalanceOption]
            raise ValueError(
                f"rebalance must be one of {allowed}, got '{v}'"
            ) from None

    @field_validator("data_source")
    @classmethod
    def _data_source_value(cls, v: str) -> str:
        try:
            return _DataSourceOption(v).value
        except ValueError:
            allowed = [e.value for e in _DataSourceOption]
            raise ValueError(
                f"data_source must be one of {allowed}, got '{v}'"
            ) from None

    @field_validator("mt5_bridge_port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError(f"mt5.bridge_port must be in [1, 65535], got {v}")
        return v
