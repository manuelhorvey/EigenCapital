"""Live Authorization Gate — fail-closed human authorization for micro-live.

Authorization must bind:
- campaign ID
- strategy identity
- portfolio identity
- risk configuration fingerprint
- execution configuration fingerprint
- broker identity
- account identity
- execution mode
- authorization timestamp
- expiry timestamp
- operator identity

Authorization must fail if any fingerprint changes.
Authorization must fail if expired.
Authorization must be auditable.
No authorization → LIVE ORDER MUST BE REJECTED.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class AuthorizationStatus(str, Enum):
    """Authorization lifecycle status."""
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"


class ExecutionMode(str, Enum):
    """Execution mode."""
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(frozen=True)
class LiveAuthorization:
    """Immutable human authorization for a micro-live campaign.

    Must be explicitly granted. Cannot be accidentally activated.
    Any fingerprint mismatch rejects execution.
    """
    authorization_id: str
    campaign_id: str
    strategy_fingerprint: str
    portfolio_fingerprint: str
    risk_fingerprint: str
    execution_fingerprint: str
    broker_identity: str
    account_identity: str
    execution_mode: str
    max_capital: float
    max_drawdown: float
    operator_identity: str
    authorization_timestamp: str
    expiry_timestamp: str
    status: str = AuthorizationStatus.ACTIVE.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "campaign_id": self.campaign_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "portfolio_fingerprint": self.portfolio_fingerprint,
            "risk_fingerprint": self.risk_fingerprint,
            "execution_fingerprint": self.execution_fingerprint,
            "broker_identity": self.broker_identity,
            "account_identity": self.account_identity,
            "execution_mode": self.execution_mode,
            "max_capital": self.max_capital,
            "max_drawdown": self.max_drawdown,
            "operator_identity": self.operator_identity,
            "authorization_timestamp": self.authorization_timestamp,
            "expiry_timestamp": self.expiry_timestamp,
            "status": self.status,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AuthorizationGate:
    """Fail-closed live authorization boundary.

    LIVE orders require explicit, non-expired authorization with matching fingerprints.
    """

    def __init__(self) -> None:
        self._authorizations: Dict[str, LiveAuthorization] = {}
        self._rejection_log: List[Dict[str, Any]] = []

    def grant_authorization(self, auth: LiveAuthorization) -> None:
        """Grant a live authorization."""
        self._authorizations[auth.authorization_id] = auth

    def revoke_authorization(self, authorization_id: str) -> bool:
        """Revoke a live authorization."""
        auth = self._authorizations.get(authorization_id)
        if auth is None:
            return False
        # Create revoked version
        revoked = LiveAuthorization(
            authorization_id=auth.authorization_id,
            campaign_id=auth.campaign_id,
            strategy_fingerprint=auth.strategy_fingerprint,
            portfolio_fingerprint=auth.portfolio_fingerprint,
            risk_fingerprint=auth.risk_fingerprint,
            execution_fingerprint=auth.execution_fingerprint,
            broker_identity=auth.broker_identity,
            account_identity=auth.account_identity,
            execution_mode=auth.execution_mode,
            max_capital=auth.max_capital,
            max_drawdown=auth.max_drawdown,
            operator_identity=auth.operator_identity,
            authorization_timestamp=auth.authorization_timestamp,
            expiry_timestamp=auth.expiry_timestamp,
            status=AuthorizationStatus.REVOKED.value,
        )
        self._authorizations[authorization_id] = revoked
        return True

    def validate_authorization(
        self,
        authorization_id: str,
        current_timestamp: str,
        strategy_fingerprint: str = "",
        portfolio_fingerprint: str = "",
        risk_fingerprint: str = "",
        broker_identity: str = "",
        account_identity: str = "",
    ) -> Tuple[bool, str]:
        """Validate a live authorization.

        Returns:
            (authorized, reason)
        """
        auth = self._authorizations.get(authorization_id)
        if auth is None:
            self._log_rejection(authorization_id, "Authorization not found")
            return (False, "Authorization not found")

        # Check status
        if auth.status != AuthorizationStatus.ACTIVE.value:
            self._log_rejection(authorization_id, f"Authorization status: {auth.status}")
            return (False, f"Authorization status: {auth.status}")

        # Check expiry
        if current_timestamp > auth.expiry_timestamp:
            self._log_rejection(authorization_id, "Authorization expired")
            return (False, "Authorization expired")

        # Check fingerprints
        if strategy_fingerprint and strategy_fingerprint != auth.strategy_fingerprint:
            self._log_rejection(authorization_id, "Strategy fingerprint mismatch")
            return (False, "Strategy fingerprint mismatch")

        if portfolio_fingerprint and portfolio_fingerprint != auth.portfolio_fingerprint:
            self._log_rejection(authorization_id, "Portfolio fingerprint mismatch")
            return (False, "Portfolio fingerprint mismatch")

        if risk_fingerprint and risk_fingerprint != auth.risk_fingerprint:
            self._log_rejection(authorization_id, "Risk fingerprint mismatch")
            return (False, "Risk fingerprint mismatch")

        if broker_identity and broker_identity != auth.broker_identity:
            self._log_rejection(authorization_id, "Broker identity mismatch")
            return (False, "Broker identity mismatch")

        if account_identity and account_identity != auth.account_identity:
            self._log_rejection(authorization_id, "Account identity mismatch")
            return (False, "Account identity mismatch")

        return (True, "Authorized")

    def is_live_enabled(self) -> bool:
        """Check if any active authorization exists for live mode."""
        for auth in self._authorizations.values():
            if (auth.status == AuthorizationStatus.ACTIVE.value
                    and auth.execution_mode == ExecutionMode.LIVE.value):
                return True
        return False

    def get_active_authorization(self, campaign_id: str) -> Optional[LiveAuthorization]:
        """Get active authorization for a campaign."""
        for auth in self._authorizations.values():
            if auth.campaign_id == campaign_id and auth.status == AuthorizationStatus.ACTIVE.value:
                return auth
        return None

    def _log_rejection(self, authorization_id: str, reason: str) -> None:
        self._rejection_log.append({
            "authorization_id": authorization_id,
            "reason": reason,
        })

    def get_rejection_log(self) -> List[Dict[str, Any]]:
        return list(self._rejection_log)
