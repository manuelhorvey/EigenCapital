"""Controlled Live Readiness / Micro-Live Qualification.

Builds the controlled live execution boundary for EigenCapital.
Micro-live only. No unrestricted live trading.
"""

from eigencapital.live.broker import (
    LiveBrokerAdapter,
    BrokerConfig,
    BrokerStatus,
    BrokerErrorType,
)
from eigencapital.live.risk import (
    MicroLiveRiskEnvelope,
    MicroLiveLimits,
    LivePreflight,
    StopReason,
    PreflightCheck,
)
from eigencapital.live.authorization import (
    LiveAuthorization,
    AuthorizationGate,
    AuthorizationStatus,
    ExecutionMode,
)
from eigencapital.live.campaign import (
    MicroLiveCampaign,
    CampaignManager,
    CampaignStatus,
)
from eigencapital.live.comparison import (
    DivergenceRecord,
    DivergenceAnalyzer,
    DivergenceCategory,
    DivergenceSeverity,
    ComparisonResult,
)

__all__ = [
    "LiveBrokerAdapter",
    "BrokerConfig",
    "BrokerStatus",
    "BrokerErrorType",
    "MicroLiveRiskEnvelope",
    "MicroLiveLimits",
    "LivePreflight",
    "StopReason",
    "PreflightCheck",
    "LiveAuthorization",
    "AuthorizationGate",
    "AuthorizationStatus",
    "ExecutionMode",
    "MicroLiveCampaign",
    "CampaignManager",
    "CampaignStatus",
    "DivergenceRecord",
    "DivergenceAnalyzer",
    "DivergenceCategory",
    "DivergenceSeverity",
    "ComparisonResult",
]
