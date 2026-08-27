"""Controlled Live Readiness / Micro-Live Qualification.

Builds the controlled live execution boundary for EigenCapital.
Micro-live only. No unrestricted live trading.
"""

from eigencapital.live.authorization import (
    AuthorizationGate,
    AuthorizationStatus,
    ExecutionMode,
    LiveAuthorization,
)
from eigencapital.live.broker import (
    BrokerConfig,
    BrokerErrorType,
    BrokerStatus,
    LiveBrokerAdapter,
)
from eigencapital.live.campaign import (
    CampaignManager,
    CampaignStatus,
    MicroLiveCampaign,
)
from eigencapital.live.comparison import (
    ComparisonResult,
    DivergenceAnalyzer,
    DivergenceCategory,
    DivergenceRecord,
    DivergenceSeverity,
)
from eigencapital.live.risk import (
    LivePreflight,
    MicroLiveLimits,
    MicroLiveRiskEnvelope,
    PreflightCheck,
    StopReason,
)

__all__ = [
    "AuthorizationGate",
    "AuthorizationStatus",
    "BrokerConfig",
    "BrokerErrorType",
    "BrokerStatus",
    "CampaignManager",
    "CampaignStatus",
    "ComparisonResult",
    "DivergenceAnalyzer",
    "DivergenceCategory",
    "DivergenceRecord",
    "DivergenceSeverity",
    "ExecutionMode",
    "LiveAuthorization",
    "LiveBrokerAdapter",
    "LivePreflight",
    "MicroLiveCampaign",
    "MicroLiveLimits",
    "MicroLiveRiskEnvelope",
    "PreflightCheck",
    "StopReason",
]
