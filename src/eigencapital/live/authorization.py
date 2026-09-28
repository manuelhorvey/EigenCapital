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

Cryptographic signing (HMAC-SHA256)
-----------------------------------
Every authorization record carries an HMAC-SHA256 ``signature`` computed over
the canonical JSON payload of the record (sorted keys, ``signature`` excluded):

- Signing key source: the ``EIGENCAPITAL_AUTHORIZATION_SIGNING_KEY``
  environment variable (``SIGNING_KEY_ENV_VAR``). The key is never hardcoded
  and never written to a committed config file.
- Verification is fail-closed: a record whose signature does not verify, or
  that carries a signature while no key is configured, is REJECTED. A missing
  key is never treated as "accept everything".
- Legacy transition window: records persisted by pre-signing code (no
  signature field) are accepted only while ``current_timestamp`` is at or
  before ``LEGACY_UNSIGNED_WINDOW_END`` (the same timestamp used for the
  expiry check) and are logged as legacy on every acceptance. After that
  instant every unsigned record is rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# HMAC-SHA256 signing key for authorization records. Environment-only secret:
# read at call time, never defaulted, never persisted to config.
SIGNING_KEY_ENV_VAR = "EIGENCAPITAL_AUTHORIZATION_SIGNING_KEY"

# End of the accept-then-reject transition window for records written by
# pre-signing code (no ``signature`` field). Deliberately time-bounded: after
# this instant an unsigned record is rejected unconditionally (fail-closed).
LEGACY_UNSIGNED_WINDOW_END = "2026-12-31T23:59:59"


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
    signature: str = ""

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
            "signature": self.signature,
        }

    def compute_fingerprint(self) -> str:
        """SHA-256 over the canonical payload (signature excluded).

        Signing never changes the fingerprint: the fingerprint identifies the
        authorization content, the signature authenticates it.
        """
        return hashlib.sha256(_canonical_payload(self)).hexdigest()


def load_signing_key() -> str | None:
    """Read the HMAC-SHA256 signing key from ``SIGNING_KEY_ENV_VAR``.

    Returns ``None`` when the variable is unset or blank. Callers must treat
    ``None`` as fail-closed: no signature can be produced or verified.
    """
    key = os.environ.get(SIGNING_KEY_ENV_VAR, "").strip()
    return key or None


def _canonical_payload(auth: LiveAuthorization) -> bytes:
    """Canonical bytes covered by the HMAC: every field except the signature."""
    data = {key: value for key, value in auth.to_dict().items() if key != "signature"}
    return json.dumps(data, sort_keys=True).encode("utf-8")


def _hmac_hex(payload: bytes, signing_key: str) -> str:
    return hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_authorization(auth: LiveAuthorization, signing_key: str | None = None) -> LiveAuthorization:
    """Return a copy of ``auth`` carrying an HMAC-SHA256 ``signature``.

    Args:
        auth: Record to sign.
        signing_key: Explicit key; when ``None`` the environment is consulted.

    Raises:
        ValueError: No signing key is available. Signing fails closed — an
            unsigned record is never produced silently on request to sign.
    """
    key = signing_key if signing_key is not None else load_signing_key()
    if not key:
        raise ValueError(f"Cannot sign authorization record: {SIGNING_KEY_ENV_VAR} is not set")
    return replace(auth, signature=_hmac_hex(_canonical_payload(auth), key))


class AuthorizationGate:
    """Fail-closed live authorization boundary.

    LIVE orders require explicit, non-expired authorization with matching
    fingerprints and a valid HMAC-SHA256 signature (see module docstring).
    """

    def __init__(self) -> None:
        self._authorizations: Dict[str, LiveAuthorization] = {}
        self._rejection_log: List[Dict[str, Any]] = []

    def grant_authorization(self, auth: LiveAuthorization) -> None:
        """Grant a live authorization.

        Unsigned records are signed with the configured key on ingest so every
        newly granted record carries an HMAC-SHA256 signature. Records that
        already carry a signature are stored as received and never re-signed
        here — re-signing would launder a tampered payload; a stale signature
        is caught by :meth:`validate_authorization` instead. Without a
        configured key the record stays unsigned and is then only admissible
        inside the legacy transition window.
        """
        if not auth.signature:
            key = load_signing_key()
            if key:
                auth = sign_authorization(auth, key)
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
            signature="",  # the old signature no longer matches the revoked payload
        )
        key = load_signing_key()
        if key:
            # Re-sign so the revoked record stays verifiable after the legacy window.
            revoked = sign_authorization(revoked, key)
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

        Signature verification runs first (authenticate before evaluating
        status, expiry or fingerprints) and is fail-closed.

        Returns:
            (authorized, reason)
        """
        auth = self._authorizations.get(authorization_id)
        if auth is None:
            self._log_rejection(authorization_id, "Authorization not found")
            return (False, "Authorization not found")

        # Check signature (fail-closed)
        signature_reason = self._check_signature(auth, current_timestamp)
        if signature_reason is not None:
            self._log_rejection(authorization_id, signature_reason)
            return (False, signature_reason)

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
        """Check if any active authorization exists for live mode.

        Records whose signature does not verify never enable live (the
        legacy-window decision for unsigned records is made in
        :meth:`validate_authorization`, the enforcement point for orders).
        """
        for auth in self._authorizations.values():
            if (
                auth.status == AuthorizationStatus.ACTIVE.value
                and auth.execution_mode == ExecutionMode.LIVE.value
                and self._signature_intact(auth)
            ):
                return True
        return False

    def get_active_authorization(self, campaign_id: str) -> LiveAuthorization | None:
        """Get active authorization for a campaign.

        Returns ``None`` rather than a record whose signature fails
        verification (fail-closed).
        """
        for auth in self._authorizations.values():
            if (
                auth.campaign_id == campaign_id
                and auth.status == AuthorizationStatus.ACTIVE.value
                and self._signature_intact(auth)
            ):
                return auth
        return None

    def _check_signature(self, auth: LiveAuthorization, current_timestamp: str) -> str | None:
        """Verify the record signature; return a rejection reason or ``None``.

        Fail-closed rules:

        - signature present, key configured: constant-time HMAC compare;
          mismatch (tampered payload or foreign key) rejects.
        - signature present, key missing: rejects — an unverifiable record is
          never accepted just because the secret is unavailable.
        - signature missing: accepted only while ``current_timestamp`` is at
          or before ``LEGACY_UNSIGNED_WINDOW_END`` (legacy transition window,
          evaluated against the same timestamp used for the expiry check) and
          logged as legacy; rejected afterwards.
        """
        if auth.signature:
            key = load_signing_key()
            if not key:
                return f"Signature unverifiable: {SIGNING_KEY_ENV_VAR} is not set"
            if not hmac.compare_digest(_hmac_hex(_canonical_payload(auth), key), auth.signature):
                return "Signature verification failed (record tampered or signed with a different key)"
            return None

        if current_timestamp > LEGACY_UNSIGNED_WINDOW_END:
            return (
                f"Unsigned authorization rejected: legacy window ended {LEGACY_UNSIGNED_WINDOW_END} "
                "(re-grant the record with a signature)"
            )
        logger.warning(
            "legacy unsigned authorization accepted during transition window: "
            "authorization_id=%s current_timestamp=%s window_end=%s",
            auth.authorization_id,
            current_timestamp,
            LEGACY_UNSIGNED_WINDOW_END,
        )
        return None

    def _signature_intact(self, auth: LiveAuthorization) -> bool:
        """True unless the record carries a signature that fails verification.

        Unsigned records return ``True`` here so they remain visible to
        callers; their acceptance is gated by the legacy window in
        :meth:`validate_authorization`.
        """
        if not auth.signature:
            return True
        key = load_signing_key()
        if not key:
            return False
        return hmac.compare_digest(_hmac_hex(_canonical_payload(auth), key), auth.signature)

    def _log_rejection(self, authorization_id: str, reason: str) -> None:
        self._rejection_log.append(
            {
                "authorization_id": authorization_id,
                "reason": reason,
            }
        )

    def get_rejection_log(self) -> List[Dict[str, Any]]:
        return list(self._rejection_log)
