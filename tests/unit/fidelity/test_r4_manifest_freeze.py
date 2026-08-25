"""R4 Manifest Freeze Guard — CI fails if any frozen R4 parameter drifts.

The entire R4 qualification chain (campaign → replay parity → paper
fidelity 7/7 → shadow → micro-live → production qualification) attests
to ONE configuration. This test makes any silent edit to that
configuration fail loudly instead of invalidating the ladder quietly.

Re-freeze protocol: if a parameter legitimately changes, this is a NEW
campaign — re-run the ladder, regenerate downstream artifacts, then
update the pinned constants here in the same commit.
"""

import json
from pathlib import Path

import pytest

from eigencapital.fidelity.r4_manifest import R4ConfigManifest

# Full sha256 of the bare manifest — identical to manifest_identity in
# reports/production_qualification_PQ-aaab6c00dc05.json.
FROZEN_PQ_IDENTITY = (
    "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"
)

# 16-hex prefix recorded by the original R4 campaign run.
CAMPAIGN_FREEZE_PREFIX = "ee0d7a03021eeb4f"

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestManifestIdentity:
    """The reproducible frozen identity."""

    def test_deterministic_across_instances(self):
        assert (
            R4ConfigManifest().compute_identity()
            == R4ConfigManifest().compute_identity()
        )

    def test_identity_matches_production_qualification_artifact(self):
        current = R4ConfigManifest().compute_identity()
        assert current == FROZEN_PQ_IDENTITY, (
            "R4ConfigManifest defaults drifted from the production-"
            "qualified identity. This invalidates replay parity, paper "
            "fidelity, shadow qualification and micro-live evidence. "
            "If intentional: re-run the full fidelity ladder, regenerate "
            "artifacts, and update FROZEN_PQ_IDENTITY in this test."
        )

    def test_to_dict_embeds_current_identity(self):
        m = R4ConfigManifest()
        assert m.to_dict()["manifest_identity"] == m.compute_identity()


class TestFrozenSemantics:
    """Defense in depth: pin the load-bearing parameters by name so a
    failure message identifies WHAT changed, not just THAT it changed."""

    def _manifest(self) -> R4ConfigManifest:
        return R4ConfigManifest()

    def test_universe_fifteen_instruments(self):
        universe = self._manifest().universe
        assert len(universe) == 15
        assert universe["EURUSDm"] == "forex"
        assert universe["XAUUSDm"] == "metals"
        assert universe["US500m"] == "indices"
        assert universe["BTCUSDm"] == "crypto"

    def test_signal_parameters(self):
        m = self._manifest()
        assert m.signal_lookback_short == 63
        assert m.signal_lookback_long == 252
        assert m.signal_combination == "risk_conditioned"

    def test_risk_parameters(self):
        m = self._manifest()
        assert m.crypto_max_allocation == pytest.approx(0.10)
        assert m.asset_risk_limit == pytest.approx(0.02)
        assert m.drawdown_control_threshold == pytest.approx(-0.15)
        assert m.drawdown_control_reduction == pytest.approx(0.50)
        assert m.vol_target_annual == pytest.approx(0.10)
        assert m.risk_parity_method == "equal_risk_contribution"

    def test_execution_and_cost_parameters(self):
        m = self._manifest()
        assert m.transaction_cost_bps == pytest.approx(10.0)
        assert m.slippage_bps == pytest.approx(5.0)
        assert m.rebalance_frequency == "weekly"
        assert m.cost_model_version == "R4.0"

    def test_validation_gates(self):
        m = self._manifest()
        assert m.walk_forward_folds == 5
        assert m.stress_max_dd_threshold == pytest.approx(-0.25)
        assert m.min_sharpe_threshold == pytest.approx(0.5)


class TestCampaignArtifactGuard:
    """The original campaign's recorded freeze prefix must never change."""

    def test_campaign_r4_results_freeze_hash_untouched(self):
        path = REPO_ROOT / "docs" / "research" / "CAMPAIGN_R4_RESULTS.json"
        assert path.exists(), f"missing campaign artifact: {path}"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["freeze_hash"] == CAMPAIGN_FREEZE_PREFIX, (
            "CAMPAIGN_R4_RESULTS.json freeze_hash was edited. Historical "
            "research artifacts are immutable records; edits here break "
            "the provenance chain."
        )
