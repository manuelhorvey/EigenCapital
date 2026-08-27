"""Runtime Fingerprint Verifier — fail-closed configuration integrity.

Verifies at startup and every cycle that:
1. R4 manifest fingerprint matches frozen value
2. RiskPolicy fingerprint matches expected
3. LiveRiskConfig fingerprint matches expected
4. Broker config matches expected
5. Strategy parameters match manifest

Design rules:
- Fail closed: any verification failure blocks ALL trading
- No silent substitution of fingerprint_match=True
- Every verification result is auditable
- Mutations to any component must be detected
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC
from enum import Enum
from typing import Any, Dict, List

from eigencapital.config import EigenCapitalConfig, LiveRiskConfig
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.risk.policy import RiskPolicy


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    ERROR = "error"
    NOT_LOADED = "not_loaded"


@dataclass(frozen=True)
class FingerprintCheck:
    """Result of a single fingerprint verification."""

    component: str
    status: str
    expected: str
    observed: str
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "expected": self.expected[:16] if self.expected else "",
            "observed": self.observed[:16] if self.observed else "",
            "message": self.message,
        }


@dataclass(frozen=True)
class FingerprintVerificationResult:
    """Complete fingerprint verification result."""

    all_verified: bool
    checks: tuple  # tuple of FingerprintCheck
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_verified": self.all_verified,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp,
        }


class FingerprintVerifier:
    """Runtime fingerprint verification — fail closed.

    Must be initialized with:
    - The frozen R4 manifest
    - The active RiskPolicy
    - The active LiveRiskConfig
    - The active EigenCapitalConfig

    Any mismatch produces VERIFICATION_FAILED which blocks trading.
    """

    def __init__(
        self,
        config: EigenCapitalConfig | None = None,
        manifest: R4ConfigManifest | None = None,
        risk_policy: RiskPolicy | None = None,
        live_risk: LiveRiskConfig | None = None,
    ) -> None:
        self._config = config
        self._manifest = manifest or R4ConfigManifest()
        self._risk_policy = risk_policy or RiskPolicy()
        self._live_risk = live_risk or LiveRiskConfig()
        self._frozen_manifest_fp = self._manifest.compute_identity()
        self._frozen_risk_fp = self._compute_risk_fingerprint()
        self._frozen_live_risk_fp = self._live_risk.compute_fingerprint()
        self._frozen_config_fp = self._compute_config_fingerprint()
        self._verification_log: List[Dict[str, Any]] = []
        self._max_log_entries = 100  # Bounded retention

    def _compute_risk_fingerprint(self) -> str:
        """Compute deterministic fingerprint of RiskPolicy."""
        data = self._risk_policy.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _compute_config_fingerprint(self) -> str:
        """Compute deterministic fingerprint of the full config."""
        if self._config is None:
            return ""
        data = self._config.to_dict()
        # Remove volatile fields
        data.pop("environment", None)
        payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def verify_all(self) -> FingerprintVerificationResult:
        """Run all fingerprint verifications. Fail closed on any error."""
        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        checks: List[FingerprintCheck] = []

        # 1. R4 Manifest fingerprint
        try:
            current_fp = self._manifest.compute_identity()
            match = current_fp == self._frozen_manifest_fp
            checks.append(
                FingerprintCheck(
                    component="r4_manifest",
                    status=VerificationStatus.VERIFIED.value if match else VerificationStatus.MISMATCH.value,
                    expected=self._frozen_manifest_fp,
                    observed=current_fp,
                    message="R4 manifest fingerprint matches" if match else "R4 manifest fingerprint MISMATCH",
                )
            )
        except Exception as e:
            checks.append(
                FingerprintCheck(
                    component="r4_manifest",
                    status=VerificationStatus.ERROR.value,
                    expected=self._frozen_manifest_fp,
                    observed="",
                    message=f"Cannot compute manifest fingerprint: {e}",
                )
            )

        # 2. RiskPolicy fingerprint
        try:
            current_risk_fp = self._compute_risk_fingerprint()
            match = current_risk_fp == self._frozen_risk_fp
            checks.append(
                FingerprintCheck(
                    component="risk_policy",
                    status=VerificationStatus.VERIFIED.value if match else VerificationStatus.MISMATCH.value,
                    expected=self._frozen_risk_fp,
                    observed=current_risk_fp,
                    message="RiskPolicy fingerprint matches" if match else "RiskPolicy fingerprint MISMATCH",
                )
            )
        except Exception as e:
            checks.append(
                FingerprintCheck(
                    component="risk_policy",
                    status=VerificationStatus.ERROR.value,
                    expected=self._frozen_risk_fp,
                    observed="",
                    message=f"Cannot compute risk fingerprint: {e}",
                )
            )

        # 3. LiveRiskConfig fingerprint
        try:
            current_lr_fp = self._live_risk.compute_fingerprint()
            match = current_lr_fp == self._frozen_live_risk_fp
            checks.append(
                FingerprintCheck(
                    component="live_risk",
                    status=VerificationStatus.VERIFIED.value if match else VerificationStatus.MISMATCH.value,
                    expected=self._frozen_live_risk_fp,
                    observed=current_lr_fp,
                    message="LiveRiskConfig fingerprint matches" if match else "LiveRiskConfig fingerprint MISMATCH",
                )
            )
        except Exception as e:
            checks.append(
                FingerprintCheck(
                    component="live_risk",
                    status=VerificationStatus.ERROR.value,
                    expected=self._frozen_live_risk_fp,
                    observed="",
                    message=f"Cannot compute live risk fingerprint: {e}",
                )
            )

        # 4. Strategy version
        version_ok = self._manifest.strategy_version == "R4.0"
        checks.append(
            FingerprintCheck(
                component="strategy_version",
                status=VerificationStatus.VERIFIED.value if version_ok else VerificationStatus.MISMATCH.value,
                expected="R4.0",
                observed=self._manifest.strategy_version,
                message="Strategy version frozen at R4.0" if version_ok else "Strategy version MISMATCH",
            )
        )

        # 5. Config fingerprint (if config loaded)
        if self._config is not None:
            try:
                current_cfg_fp = self._compute_config_fingerprint()
                match = current_cfg_fp == self._frozen_config_fp
                checks.append(
                    FingerprintCheck(
                        component="config",
                        status=VerificationStatus.VERIFIED.value if match else VerificationStatus.MISMATCH.value,
                        expected=self._frozen_config_fp,
                        observed=current_cfg_fp,
                        message="Config fingerprint matches"
                        if match
                        else "Config fingerprint MISMATCH — configuration drift detected",
                    )
                )
            except Exception as e:
                checks.append(
                    FingerprintCheck(
                        component="config",
                        status=VerificationStatus.ERROR.value,
                        expected=self._frozen_config_fp,
                        observed="",
                        message=f"Cannot compute config fingerprint: {e}",
                    )
                )

        all_verified = all(c.status == VerificationStatus.VERIFIED.value for c in checks)
        result = FingerprintVerificationResult(
            all_verified=all_verified,
            checks=tuple(checks),
            timestamp=now,
        )

        self._verification_log.append(result.to_dict())
        # Bounded retention
        if len(self._verification_log) > self._max_log_entries:
            self._verification_log = self._verification_log[-self._max_log_entries :]
        return result

    @property
    def frozen_manifest_fingerprint(self) -> str:
        return self._frozen_manifest_fp

    @property
    def frozen_risk_fingerprint(self) -> str:
        return self._frozen_risk_fp

    @property
    def frozen_live_risk_fingerprint(self) -> str:
        return self._frozen_live_risk_fp

    @property
    def verification_log(self) -> List[Dict[str, Any]]:
        return list(self._verification_log)
