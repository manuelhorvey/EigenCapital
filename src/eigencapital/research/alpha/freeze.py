"""Research Campaign Freeze — frozen manifest that prevents environment contamination.

Before the first hypothesis runs, freeze a campaign manifest containing:
- git_commit
- data_snapshot_id
- feature_registry_version
- hypothesis_library_hash
- trial_registry_hash
- cost_model_version
- universe_definition
- evaluation_windows
- validation_config
- stress_config
- multiple_testing_config
- random_seed_policy
- execution_engine_version

The campaign refuses to run if foundational identities change without
creating a new campaign.

Protects against: "Did we modify the environment in which the hypothesis
was tested after seeing the result?"
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


class FreezeStatus(str, Enum):
    """Campaign freeze status."""

    INTACT = "intact"
    VIOLATED = "violated"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class CampaignFreezeManifest:
    """Immutable frozen manifest for a research campaign.

    If any of these change without creating a new campaign,
    the campaign is considered contaminated.
    """

    campaign_id: str
    git_commit: str
    data_snapshot_id: str
    feature_registry_version: str
    hypothesis_library_hash: str
    trial_registry_hash: str
    cost_model_version: str
    universe_definition_hash: str
    evaluation_windows_hash: str
    validation_config_hash: str
    stress_config_hash: str
    multiple_testing_config_hash: str
    random_seed_policy: str
    execution_engine_version: str
    frozen_timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "git_commit": self.git_commit,
            "data_snapshot_id": self.data_snapshot_id,
            "feature_registry_version": self.feature_registry_version,
            "hypothesis_library_hash": self.hypothesis_library_hash,
            "trial_registry_hash": self.trial_registry_hash,
            "cost_model_version": self.cost_model_version,
            "universe_definition_hash": self.universe_definition_hash,
            "evaluation_windows_hash": self.evaluation_windows_hash,
            "validation_config_hash": self.validation_config_hash,
            "stress_config_hash": self.stress_config_hash,
            "multiple_testing_config_hash": self.multiple_testing_config_hash,
            "random_seed_policy": self.random_seed_policy,
            "execution_engine_version": self.execution_engine_version,
        }

    def compute_manifest_hash(self) -> str:
        """Deterministic hash of the entire frozen manifest."""
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def check_integrity(self, current: CampaignFreezeManifest) -> Dict[str, Any]:
        """Check if current environment matches the frozen manifest.

        Returns:
            {"intact": bool, "violations": [...], "details": str}
        """
        violations = []

        if self.git_commit != current.git_commit:
            violations.append("git_commit")
        if self.data_snapshot_id != current.data_snapshot_id:
            violations.append("data_snapshot_id")
        if self.feature_registry_version != current.feature_registry_version:
            violations.append("feature_registry_version")
        if self.hypothesis_library_hash != current.hypothesis_library_hash:
            violations.append("hypothesis_library_hash")
        if self.trial_registry_hash != current.trial_registry_hash:
            violations.append("trial_registry_hash")
        if self.cost_model_version != current.cost_model_version:
            violations.append("cost_model_version")
        if self.universe_definition_hash != current.universe_definition_hash:
            violations.append("universe_definition_hash")
        if self.evaluation_windows_hash != current.evaluation_windows_hash:
            violations.append("evaluation_windows_hash")
        if self.validation_config_hash != current.validation_config_hash:
            violations.append("validation_config_hash")
        if self.stress_config_hash != current.stress_config_hash:
            violations.append("stress_config_hash")
        if self.multiple_testing_config_hash != current.multiple_testing_config_hash:
            violations.append("multiple_testing_config_hash")
        if self.execution_engine_version != current.execution_engine_version:
            violations.append("execution_engine_version")

        return {
            "intact": len(violations) == 0,
            "violations": violations,
            "details": f"Violations: {', '.join(violations)}" if violations else "Manifest intact",
        }


class FreezeRegistry:
    """Registry of campaign freeze manifests with violation tracking."""

    def __init__(self) -> None:
        self._manifests: Dict[str, CampaignFreezeManifest] = {}
        self._violations: List[Dict[str, Any]] = []

    def freeze(self, manifest: CampaignFreezeManifest) -> None:
        """Register a frozen campaign manifest."""
        self._manifests[manifest.campaign_id] = manifest

    def get(self, campaign_id: str) -> CampaignFreezeManifest | None:
        """Get a frozen manifest."""
        return self._manifests.get(campaign_id)

    def validate(self, campaign_id: str, current: CampaignFreezeManifest) -> Dict[str, Any]:
        """Validate that current environment matches frozen manifest.

        Returns:
            {"intact": bool, "violations": [...], "campaign_id": str}
        """
        frozen = self._manifests.get(campaign_id)
        if frozen is None:
            result = {
                "intact": False,
                "violations": ["manifest_not_found"],
                "campaign_id": campaign_id,
                "details": f"No frozen manifest for campaign {campaign_id}",
            }
            self._violations.append(result)
            return result

        check = frozen.check_integrity(current)
        result = {
            "intact": check["intact"],
            "violations": check["violations"],
            "campaign_id": campaign_id,
            "details": check["details"],
        }
        if not check["intact"]:
            self._violations.append(result)
        return result

    def get_violations(self) -> List[Dict[str, Any]]:
        return list(self._violations)

    def create_default_manifest(
        self,
        campaign_id: str,
        git_commit: str = "",
        frozen_timestamp: str = "",
        **overrides: Any,
    ) -> CampaignFreezeManifest:
        """Create a default freeze manifest with placeholder hashes.

        In production, these would be computed from actual configuration.
        """
        defaults = {
            "campaign_id": campaign_id,
            "git_commit": git_commit,
            "data_snapshot_id": "v1",
            "feature_registry_version": "v1",
            "hypothesis_library_hash": "placeholder",
            "trial_registry_hash": "placeholder",
            "cost_model_version": "v1",
            "universe_definition_hash": "placeholder",
            "evaluation_windows_hash": "placeholder",
            "validation_config_hash": "placeholder",
            "stress_config_hash": "placeholder",
            "multiple_testing_config_hash": "placeholder",
            "random_seed_policy": "deterministic",
            "execution_engine_version": "v1",
            "frozen_timestamp": frozen_timestamp,
        }
        defaults.update(overrides)
        return CampaignFreezeManifest(**defaults)
