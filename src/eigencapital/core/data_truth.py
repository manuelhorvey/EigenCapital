"""Data Truth Hierarchy — platform-wide provenance for every displayed/used value.

Design rules:
- UNKNOWN, MISSING, STALE, UNAVAILABLE, CORRUPT must NEVER silently become
  0, NORMAL, SAFE, VERIFIED.
- Every metric in the platform must eventually declare its truth level.
- The dashboard data-truth matrix is the documentation of this module.
- This is a platform-wide contract, not just a dashboard rule.

Usage:
    equity = TruthfulValue(
        value=5000.00,
        level=TruthLevel.AUTHORITATIVE,
        source="mt5_account_state",
        timestamp=datetime.now(UTC),
        units="USD",
        precision=2,
    )
    assert equity.is_reliable  # True for AUTHORITATIVE and DERIVED
    assert not equity.is_usable  # False for UNAVAILABLE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Generic, TypeVar

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════
# Truth Levels — the core hierarchy
# ═══════════════════════════════════════════════════════════════════


class TruthLevel(str, Enum):
    """How authoritative is this value?

    The hierarchy from most to least trustworthy:

    AUTHORITATIVE — direct from the canonical source (broker, exchange, domain state)
    DERIVED — computed from authoritative values with a known, auditable transformation
    ESTIMATED — model-derived, has uncertainty, used for forward-looking purposes
    STALE — was authoritative but is now too old to be trusted
    UNAVAILABLE — source is unreachable or data is missing
    CORRUPT — data exists but is inconsistent, malformed, or impossible
    UNKNOWN — provenance not yet determined
    """

    AUTHORITATIVE = "AUTHORITATIVE"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CORRUPT = "CORRUPT"
    UNKNOWN = "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════
# TruthfulValue — a value with provenance
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TruthfulValue(Generic[T]):
    """A value that knows where it came from and whether it's trustworthy.

    Every important metric in EigenCapital should eventually be wrapped
    in this type. It prevents the dangerous situation where a number
    looks precise but nobody knows where it came from.
    """

    value: T | None
    level: TruthLevel = TruthLevel.UNKNOWN
    source: str = ""
    timestamp: datetime | None = None
    units: str = ""
    precision: int = 2
    transformation: str = ""  # e.g., "formatting_only", "sum_of_positions"
    stale_after_seconds: float | None = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_authoritative(self) -> bool:
        """Value is directly from the canonical source."""
        return self.level == TruthLevel.AUTHORITATIVE

    @property
    def is_derived(self) -> bool:
        """Value is computed from authoritative data."""
        return self.level == TruthLevel.DERIVED

    @property
    def is_estimated(self) -> bool:
        """Value is model-derived with uncertainty."""
        return self.level == TruthLevel.ESTIMATED

    @property
    def is_reliable(self) -> bool:
        """Value is trustworthy for decision-making."""
        return self.level in (TruthLevel.AUTHORITATIVE, TruthLevel.DERIVED)

    @property
    def is_usable(self) -> bool:
        """Value has a meaningful value (not stale, unavailable, corrupt, or unknown)."""
        return self.level in (
            TruthLevel.AUTHORITATIVE,
            TruthLevel.DERIVED,
            TruthLevel.ESTIMATED,
        )

    @property
    def is_stale(self) -> bool:
        """Value was authoritative but is now too old."""
        if self.level == TruthLevel.STALE:
            return True
        if (
            self.stale_after_seconds is not None
            and self.timestamp is not None
            and self.level in (TruthLevel.AUTHORITATIVE, TruthLevel.DERIVED)
        ):
            age = (datetime.now(UTC) - self.timestamp).total_seconds()
            return age > self.stale_after_seconds
        return False

    @property
    def display_value(self) -> str:
        """Safe display string that never silently shows 0 or NORMAL for bad data."""
        # Check level FIRST — UNKNOWN should show "—" even with None value
        if self.level == TruthLevel.UNKNOWN:
            return "—"
        if self.level == TruthLevel.STALE:
            if self.value is not None:
                return f"⚠ {self._format_value(self.value)}"
            return "⚠ Stale"
        if self.level == TruthLevel.CORRUPT:
            return "⚠ CORRUPT"
        if self.level == TruthLevel.UNAVAILABLE:
            return self._unavailable_label()
        if self.value is None:
            return self._unavailable_label()
        return self._format_value(self.value)

    def _format_value(self, val: T) -> str:
        """Format value with appropriate precision."""
        if isinstance(val, float):
            return f"{val:,.{self.precision}f}"
        return str(val)

    def _unavailable_label(self) -> str:
        """Consistent unavailable label — never 0."""
        if self.units:
            return f"No {self.units} data"
        return "No data"

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "value": self.value,
            "level": self.level.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "units": self.units,
            "precision": self.precision,
            "transformation": self.transformation,
            "display_value": self.display_value,
            "is_reliable": self.is_reliable,
            "details": self.details,
        }

    def promote_to(self, level: TruthLevel) -> None:
        """Promote the truth level (e.g., STALE -> AUTHORITATIVE after refresh)."""
        self.level = level


# ═══════════════════════════════════════════════════════════════════
# TruthRegistry — tracks provenance for all platform metrics
# ═══════════════════════════════════════════════════════════════════


class TruthRegistry:
    """Platform-wide registry of truth levels for all metrics.

    Every component registers its metrics here. The dashboard, risk
    engine, reconciliation, and health monitor all query this registry
    to determine whether a value is trustworthy.
    """

    def __init__(self) -> None:
        self._values: Dict[str, TruthfulValue[Any]] = {}

    def register(
        self,
        name: str,
        value: T | None,
        level: TruthLevel,
        source: str,
        **kwargs: Any,
    ) -> TruthfulValue[T]:
        """Register or update a metric's truth level."""
        tv = TruthfulValue(
            value=value,
            level=level,
            source=source,
            **kwargs,
        )
        self._values[name] = tv
        return tv

    def get(self, name: str) -> TruthfulValue[Any] | None:
        """Get a metric's current truth level."""
        return self._values.get(name)

    def get_all(self) -> Dict[str, TruthfulValue[Any]]:
        """Get all registered metrics."""
        return dict(self._values)

    def get_unreliable(self) -> Dict[str, TruthfulValue[Any]]:
        """Get all metrics that are NOT reliable (not AUTHORITATIVE or DERIVED)."""
        return {name: tv for name, tv in self._values.items() if not tv.is_reliable}

    def get_summary(self) -> Dict[str, str]:
        """Get a human-readable summary of all metric states."""
        return {name: f"{tv.level.value} ({tv.source})" for name, tv in self._values.items()}

    def clear(self) -> None:
        """Clear all registered metrics."""
        self._values.clear()

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, name: str) -> bool:
        return name in self._values


# ═══════════════════════════════════════════════════════════════════
# Platform Truth Constants
# ═══════════════════════════════════════════════════════════════════

# Standard sources — every metric must declare one of these
SOURCE_BROKER = "broker"
SOURCE_RISK_ENGINE = "risk_engine"
SOURCE_RECONCILIATION = "reconciliation"
SOURCE_HEALTH_MONITOR = "health_monitor"
SOURCE_EVIDENCE_PIPELINE = "evidence_pipeline"
SOURCE_BUILD_SYSTEM = "build_system"
SOURCE_DERIVED = "derived"
SOURCE_MODEL = "model"
SOURCE_MANUAL = "manual"
SOURCE_CONFIG = "config"
SOURCE_DASHBOARD = "dashboard"

# Standard staleness thresholds (seconds)
STALENESS_ACCOUNT: float = 30.0  # broker account state
STALENESS_PRICE: float = 60.0  # market data
STALENESS_POSITION: float = 300.0  # open position data
STALENESS_RISK: float = 60.0  # risk observation
STALENESS_HEALTH: float = 120.0  # health state
STALENESS_RECON: float = 3600.0  # reconciliation state
STALENESS_EVIDENCE: float = 86400.0  # evidence pipeline
STALENESS_BUILD: float = float("inf")  # build identity is static


# ═══════════════════════════════════════════════════════════════════
# Canonical metric names
# ═══════════════════════════════════════════════════════════════════


class MetricName:
    """Canonical names for all platform metrics.

    Every metric that flows through the platform should use these names.
    This prevents duplicated constants and ambiguous metric references.
    """

    # Account
    BALANCE = "account.balance"
    EQUITY = "account.equity"
    FREE_MARGIN = "account.free_margin"
    MARGIN = "account.margin"
    DRAWDOWN = "account.drawdown"
    DAILY_PNL = "account.daily_pnl"
    DAILY_LOSS_REMAINING = "account.daily_loss_remaining"
    EQUITY_HIGH_WATER = "account.equity_high_water"

    # Position
    POSITION_COUNT = "positions.count"
    POSITION_RISK = "positions.risk"
    UNREALIZED_PNL = "positions.unrealized_pnl"

    # Risk
    RISK_OVERALL = "risk.overall"
    RISK_AUTHORIZATION = "risk.authorization"
    RISK_EXPOSURE = "risk.exposure"
    RISK_CONCENTRATION = "risk.concentration"

    # Health
    HEALTH_OVERALL = "health.overall"
    HEALTH_AUTHORIZATION = "health.authorization"
    HEALTH_SUPERVISOR = "health.supervisor"
    HEALTH_BROKER = "health.broker"

    # Reconciliation
    RECON_STATE = "reconciliation.state"
    MISSING_FILLS = "reconciliation.missing_fills"
    FOREIGN_POSITIONS = "reconciliation.foreign_positions"

    # Evidence
    EVIDENCE_MATURITY = "evidence.maturity"
    QUALIFICATION_STATUS = "evidence.qualification"

    # System
    BUILD_ID = "system.build_id"
    STRATEGY_VERSION = "system.strategy_version"
    FINGERPRINT = "system.fingerprint"
