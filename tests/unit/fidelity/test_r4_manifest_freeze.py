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


# Governed parameters with mutation values used to prove that every
# parameter participates in compute_identity(). A parameter absent from
# the identity payload could drift without invalidating fingerprints.
GOVERNED_PARAMS = {
    "strategy_name": "OTHER",
    "strategy_version": "R9.9",
    "strategy_hash": "drift",
    "feature_registry_version": "9.9",
    "feature_registry_hash": "drift",
    "data_snapshot_hash": "drift",
    "data_start_date": "1999-01-01",
    "data_end_date": "1999-12-31",
    "crypto_max_allocation": 0.99,
    "asset_risk_limit": 0.99,
    "correlation_threshold": 0.99,
    "drawdown_control_threshold": -0.99,
    "drawdown_control_reduction": 0.99,
    "regime_vol_lookback": 999,
    "regime_high_vol_threshold": 0.99,
    "vol_target_annual": 0.99,
    "vol_lookback": 999,
    "risk_parity_method": "other",
    "risk_parity_rebalance": 999,
    "signal_lookback_short": 999,
    "signal_lookback_long": 999,
    "signal_combination": "other",
    "transaction_cost_bps": 99.0,
    "slippage_bps": 99.0,
    "rebalance_frequency": "yearly",
    "cost_model_version": "DRIFT",
}


class TestIdentitySensitivity:
    """Every governed parameter must be covered by compute_identity()."""

    @pytest.mark.parametrize("param,mutated", sorted(GOVERNED_PARAMS.items()))
    def test_identity_changes_on_drift(self, param, mutated):
        baseline = R4ConfigManifest().compute_identity()
        drifted = R4ConfigManifest(**{param: mutated}).compute_identity()
        assert drifted != baseline, (
            f"{param} does not participate in the manifest identity; "
            f"it can drift without invalidating qualification fingerprints"
        )

    def test_identity_changes_on_universe_drift(self):
        baseline = R4ConfigManifest().compute_identity()
        frozen = R4ConfigManifest().universe

        dropped = dict(frozen)
        del dropped["USOILm"]
        assert R4ConfigManifest(universe=dropped).compute_identity() != baseline

        reclassified = dict(frozen)
        reclassified["BTCUSDm"] = "forex"
        assert (
            R4ConfigManifest(universe=reclassified).compute_identity()
            != baseline
        )

        reordered = dict(reversed(list(frozen.items())))
        assert (
            R4ConfigManifest(universe=reordered).compute_identity()
            == baseline
        )


class TestUncoveredFields:
    """Fields outside compute_identity() are pinned explicitly."""

    def test_data_provenance_fields(self):
        m = R4ConfigManifest()
        assert m.data_source == "exness_mt5"
        assert m.data_terminal_id == "168966110"
        assert m.data_bar_count == 31790

    def test_correlation_threshold(self):
        assert R4ConfigManifest().correlation_threshold == pytest.approx(0.7)

    def test_regime_parameters(self):
        m = R4ConfigManifest()
        assert m.regime_vol_lookback == 20
        assert m.regime_high_vol_threshold == pytest.approx(0.75)

    def test_cost_model_hash_placeholder(self):
        """cost_model_hash is in neither identity nor to_dict; pin it."""
        assert R4ConfigManifest().cost_model_hash == ""


class TestUniversePartition:
    def test_asset_class_partition(self):
        classes: dict = {}
        for symbol, asset_class in R4ConfigManifest().universe.items():
            classes.setdefault(asset_class, []).append(symbol)
        assert len(classes["forex"]) == 7
        assert len(classes["metals"]) == 2
        assert len(classes["indices"]) == 3
        assert len(classes["crypto"]) == 2
        assert len(classes["energy"]) == 1

    def test_crypto_cap_consistent_with_partition(self):
        manifest = R4ConfigManifest()
        assert any(c == "crypto" for c in manifest.universe.values())
        assert 0.0 < manifest.crypto_max_allocation <= 1.0


class TestAdversarialDriftDetection:
    def test_guard_detects_subtle_float_drift(self):
        baseline = R4ConfigManifest().compute_identity()
        drifted = R4ConfigManifest(vol_target_annual=0.1000001)
        assert drifted.compute_identity() != baseline

    def test_guard_detects_string_whitespace_drift(self):
        baseline = R4ConfigManifest().compute_identity()
        drifted = R4ConfigManifest(strategy_version="R4.0 ")
        assert drifted.compute_identity() != baseline
