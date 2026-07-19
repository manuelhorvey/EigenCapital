"""Unit tests for scripts/ops/model_health_monitor.py."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# ── compute_retrain_urgency ─────────────────────────────────────────────────


@pytest.fixture
def age_results() -> list[dict]:
    """Two assets with different age profiles."""
    return [
        {
            "asset": "OLDASF",
            "model_path": "/tmp/models/OLDASF_model.json",
            "age_days": 55.0,
            "is_stale": False,
            "stale_ratio": 0.917,
            "last_modified": "2026-05-01T00:00:00+00:00",
        },
        {
            "asset": "FRESH",
            "model_path": "/tmp/models/FRESH_model.json",
            "age_days": 5.0,
            "is_stale": False,
            "stale_ratio": 0.083,
            "last_modified": "2026-06-25T00:00:00+00:00",
        },
    ]


@pytest.fixture
def psi_results() -> list[dict]:
    """One asset with stale PSI baseline, one with OK baseline."""
    return [
        {
            "asset": "OLDASF",
            "baseline_age_days": 100.0,
            "baseline_exists": True,
            "model_newer_than_baseline": True,
            "baseline_vs_model_age_gap_days": -45.0,
            "status": "baseline_stale",
        },
        {
            "asset": "FRESH",
            "baseline_age_days": 5.0,
            "baseline_exists": True,
            "model_newer_than_baseline": False,
            "baseline_vs_model_age_gap_days": 0.0,
            "status": "ok",
        },
        {
            "asset": "NOSTALE",
            "baseline_age_days": 3.0,
            "baseline_exists": True,
            "model_newer_than_baseline": False,
            "baseline_vs_model_age_gap_days": 2.0,
            "status": "ok",
        },
    ]


@pytest.fixture
def stability_results() -> list[dict]:
    """One stable asset, one insufficient-data, one unstable."""
    return [
        {
            "asset": "OLDASF",
            "n_windows": 6,
            "jaccard_top_10": 0.75,
            "spearman_rank_corr": 0.85,
            "stability_score": 0.800,
            "penalty": 0.0,
            "status": "ok",
        },
        {
            "asset": "FRESH",
            "n_windows": 1,
            "stability_score": 0.5,
            "status": "insufficient_data",
        },
        {
            "asset": "UNSTABLE",
            "n_windows": 4,
            "jaccard_top_10": 0.20,
            "spearman_rank_corr": 0.30,
            "stability_score": 0.250,
            "penalty": 5.0,
            "status": "ok",
        },
    ]


@pytest.fixture
def volume_results() -> list[dict]:
    """One high-volume asset, one low-volume."""
    return [
        {
            "asset": "OLDASF",
            "estimated_inferences": 100_000,
            "volume_ratio": 1.0,
            "is_high_volume": True,
            "status": "ok",
        },
        {
            "asset": "FRESH",
            "estimated_inferences": 1_000,
            "volume_ratio": 0.02,
            "is_high_volume": False,
            "status": "ok",
        },
    ]


class TestComputeRetrainUrgency:
    """Tests for compute_retrain_urgency — a pure function, so no mocking needed."""

    # Weight constants for reference:
    #   model_age: 0.30, psi_drift: 0.30, feature_stability: 0.20, inference_volume: 0.20
    # Default stab_score for assets without a stability entry: 0.5 → contributes 0.10

    def test_basic_scores(
        self,
        age_results: list[dict],
        psi_results: list[dict],
        stability_results: list[dict],
        volume_results: list[dict],
    ) -> None:
        """Verify urgency scores are computed correctly for known inputs."""
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        result = compute_retrain_urgency(age_results, psi_results, stability_results, volume_results)

        assert len(result) >= 3
        assert result[0]["urgency_score"] >= result[-1]["urgency_score"]

        by_asset = {r["asset"]: r for r in result}

        # OLDASF: age=0.917*0.30=0.275, psi=1.0*0.30=0.30, stab=(1-0.8)*0.20=0.04, vol=1.0*0.20=0.20
        # Total: 0.275 + 0.30 + 0.04 + 0.20 = 0.815
        oa = by_asset.get("OLDASF")
        assert oa is not None, "OLDASF should be in results"
        assert oa["urgency_score"] == pytest.approx(0.815, abs=0.01)
        assert oa["needs_retrain"] is True  # 0.815 > 0.65
        assert "psi_drift" in oa["limiting_factors"]

        # FRESH: age=0.083*0.30=0.025, psi=0.0, stab=0.5*0.20=0.10 (insufficient_data), vol=0.02*0.20=0.004
        # Total: 0.025 + 0.0 + 0.10 + 0.004 = 0.129
        fr = by_asset.get("FRESH")
        assert fr is not None, "FRESH should be in results"
        assert fr["urgency_score"] == pytest.approx(0.129, abs=0.01)
        assert fr["needs_retrain"] is False

    def test_empty_inputs(self) -> None:
        """Empty lists should produce an empty result."""
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        result = compute_retrain_urgency([], [], [], [])
        assert result == []

    def test_custom_threshold(
        self,
        age_results: list[dict],
        psi_results: list[dict],
        stability_results: list[dict],
        volume_results: list[dict],
    ) -> None:
        """Custom urgency_threshold changes needs_retrain without changing scores."""
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        result = compute_retrain_urgency(
            age_results,
            psi_results,
            stability_results,
            volume_results,
            urgency_threshold=0.9,
        )
        by_asset = {r["asset"]: r for r in result}
        oa = by_asset.get("OLDASF")
        assert oa is not None
        assert oa["needs_retrain"] is False  # 0.815 < 0.9
        assert oa["urgency_score"] == pytest.approx(0.815, abs=0.01)

    def test_asset_union_from_different_check_groups(self) -> None:
        """Assets appearing in different check groups are all included.

        NOTE: Assets without a stability entry get default stab_score=0.5,
        which contributes 0.5 * 0.20 = 0.10 to urgency.
        """
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        age = [{"asset": "A", "stale_ratio": 0.5}]
        psi = [{"asset": "B", "status": "ok"}]
        stab = [{"asset": "C", "status": "ok", "stability_score": 0.8}]
        vol: list[dict] = []

        result = compute_retrain_urgency(age, psi, stab, vol)
        by_asset = {r["asset"]: r for r in result}
        assert set(by_asset.keys()) == {"A", "B", "C"}

        # A: age=0.5*0.30=0.15, stab=0.5*0.20=0.10 (default), others=0 → total=0.25
        assert by_asset["A"]["urgency_score"] == pytest.approx(0.25, abs=0.01)
        assert by_asset["A"]["needs_retrain"] is False

    def test_limiting_factors_empty_when_below_threshold(self) -> None:
        """No limiting factors when all scores are low."""
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        age = [{"asset": "LOW", "stale_ratio": 0.1}]
        result = compute_retrain_urgency(age, [], [], [])
        assert result[0]["limiting_factors"] == []

    def test_psi_stale_contributes_urgency(self) -> None:
        """PSI baseline_stale status adds psi_drift=1.0 contrib.

        NOTE: Without a stability entry, default stab_score=0.5 contributes
        0.5 * 0.20 = 0.10 to the total urgency.
        """
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        age = [{"asset": "T", "stale_ratio": 0.0}]
        psi = [{"asset": "T", "status": "baseline_stale"}]
        result = compute_retrain_urgency(age, psi, [], [])
        entry = result[0]
        assert entry["contributors"]["psi_drift"] == 1.0
        # psi=1.0*0.30=0.30 + stab=0.5*0.20=0.10 (default) = 0.40
        assert entry["urgency_score"] == pytest.approx(0.40, abs=0.01)
        assert "psi_drift" in entry["limiting_factors"]

    def test_inference_volume_at_max(self) -> None:
        """volume_ratio=1.0 contributes 0.20 to urgency (1.0*0.20).

        NOTE: Without a stability entry, default stab_score=0.5 contributes
        0.5 * 0.20 = 0.10 to the total urgency.
        """
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        age = [{"asset": "V", "stale_ratio": 0.0}]
        vol = [{"asset": "V", "volume_ratio": 1.0}]
        result = compute_retrain_urgency(age, [], [], vol)
        entry = result[0]
        assert entry["contributors"]["inference_volume"] == 1.0
        # vol=1.0*0.20=0.20 + stab=0.5*0.20=0.10 (default) = 0.30
        assert entry["urgency_score"] == pytest.approx(0.30, abs=0.01)

    def test_sort_order_descending(self) -> None:
        """Results are sorted by urgency descending."""
        from scripts.ops.model_health_monitor import compute_retrain_urgency

        age = [
            {"asset": "HIGH", "stale_ratio": 1.0},
            {"asset": "MID", "stale_ratio": 0.5},
            {"asset": "LOW", "stale_ratio": 0.1},
        ]
        result = compute_retrain_urgency(age, [], [], [])
        scores = [r["urgency_score"] for r in result]
        assert scores == sorted(scores, reverse=True)
        assert result[0]["asset"] == "HIGH"
        assert result[-1]["asset"] == "LOW"


# ── check_model_ages with mock files ────────────────────────────────────────


class TestCheckModelAges:
    """Tests for check_model_ages — requires temp model files with controlled mtime."""

    def test_no_model_files(self, tmp_path: Path) -> None:
        """Empty model directory should return empty list."""
        import scripts.ops.model_health_monitor as mhm

        original_dir = mhm.MODEL_DIR
        try:
            mhm.MODEL_DIR = tmp_path
            result = mhm.check_model_ages(max_age_days=60)
            assert result == []
        finally:
            mhm.MODEL_DIR = original_dir

    def test_single_fresh_model(self, tmp_path: Path) -> None:
        """A model file just created should have age near 0 and not be stale."""
        import scripts.ops.model_health_monitor as mhm

        original_dir = mhm.MODEL_DIR
        try:
            mhm.MODEL_DIR = tmp_path
            (tmp_path / "AUDUSD_model.json").write_text("{}")
            result = mhm.check_model_ages(max_age_days=60)
            assert len(result) == 1
            assert result[0]["asset"] == "AUDUSD"
            assert result[0]["age_days"] < 0.01
            assert result[0]["is_stale"] is False
            assert result[0]["stale_ratio"] < 0.001
        finally:
            mhm.MODEL_DIR = original_dir

    def test_stale_model(self, tmp_path: Path) -> None:
        """A model file with old mtime should be stale."""
        import scripts.ops.model_health_monitor as mhm

        original_dir = mhm.MODEL_DIR
        try:
            mhm.MODEL_DIR = tmp_path
            model_file = tmp_path / "GBPUSD_model.json"
            model_file.write_text("{}")
            old_time = time.time() - 100 * 86400
            os.utime(str(model_file), (old_time, old_time))
            result = mhm.check_model_ages(max_age_days=60)
            assert len(result) == 1
            assert result[0]["is_stale"] is True
            assert result[0]["stale_ratio"] == 1.0  # capped
        finally:
            mhm.MODEL_DIR = original_dir

    def test_partial_stale_model(self, tmp_path: Path) -> None:
        """Model with age at 50% of threshold should have stale_ratio=0.5."""
        import scripts.ops.model_health_monitor as mhm

        original_dir = mhm.MODEL_DIR
        try:
            mhm.MODEL_DIR = tmp_path
            model_file = tmp_path / "EURUSD_model.json"
            model_file.write_text("{}")
            old_time = time.time() - 30 * 86400
            os.utime(str(model_file), (old_time, old_time))
            result = mhm.check_model_ages(max_age_days=60)
            assert result[0]["stale_ratio"] == 0.5
            assert result[0]["is_stale"] is False
        finally:
            mhm.MODEL_DIR = original_dir

    def test_multiple_assets(self, tmp_path: Path) -> None:
        """Multiple model files are all returned."""
        import scripts.ops.model_health_monitor as mhm

        original_dir = mhm.MODEL_DIR
        try:
            mhm.MODEL_DIR = tmp_path
            for asset in ("AUDUSD", "EURUSD", "GBPUSD"):
                (tmp_path / f"{asset}_model.json").write_text("{}")
            result = mhm.check_model_ages(max_age_days=60)
            assert len(result) == 3
            assets = {r["asset"] for r in result}
            assert assets == {"AUDUSD", "EURUSD", "GBPUSD"}
        finally:
            mhm.MODEL_DIR = original_dir


# ── check_psi_baseline_staleness with mock files ────────────────────────────


class TestCheckPsiBaselineStaleness:
    """Tests for check_psi_baseline_staleness — requires PSI baseline parquet files."""

    def test_no_psi_dir(self) -> None:
        """Missing psi_baseline directory returns empty list."""
        import scripts.ops.model_health_monitor as mhm

        original_data_dir = mhm.DATA_DIR
        try:
            mhm.DATA_DIR = Path("/nonexistent")
            result = mhm.check_psi_baseline_staleness()
            assert result == []
        finally:
            mhm.DATA_DIR = original_data_dir

    def test_empty_psi_dir(self, tmp_path: Path) -> None:
        """Empty psi_baseline directory returns empty list."""
        import scripts.ops.model_health_monitor as mhm

        original_data_dir = mhm.DATA_DIR
        try:
            psi_dir = tmp_path / "live" / "psi_baseline"
            psi_dir.mkdir(parents=True)
            mhm.DATA_DIR = tmp_path
            result = mhm.check_psi_baseline_staleness()
            assert result == []
        finally:
            mhm.DATA_DIR = original_data_dir

    def test_psi_baseline_ok(self, tmp_path: Path) -> None:
        """PSI baseline same age or newer than model → status=ok."""
        import scripts.ops.model_health_monitor as mhm

        original_data_dir = mhm.DATA_DIR
        original_model_dir = mhm.MODEL_DIR
        try:
            model_dir = tmp_path / "models"
            model_dir.mkdir()
            model_file = model_dir / "AUDUSD_model.json"
            model_file.write_text("{}")
            mhm.MODEL_DIR = model_dir

            psi_dir = tmp_path / "live" / "psi_baseline"
            psi_dir.mkdir(parents=True)
            baseline_file = psi_dir / "AUDUSD.parquet"
            baseline_file.write_text("dummy")

            mhm.DATA_DIR = tmp_path

            result = mhm.check_psi_baseline_staleness()
            assert len(result) == 1
            assert result[0]["asset"] == "AUDUSD"
            assert result[0]["status"] == "ok"
            assert result[0]["baseline_exists"] is True
        finally:
            mhm.DATA_DIR = original_data_dir
            mhm.MODEL_DIR = original_model_dir

    def test_psi_baseline_stale(self, tmp_path: Path) -> None:
        """PSI baseline older than model by >1 day → status=baseline_stale."""
        import scripts.ops.model_health_monitor as mhm

        original_data_dir = mhm.DATA_DIR
        original_model_dir = mhm.MODEL_DIR
        try:
            model_dir = tmp_path / "models"
            model_dir.mkdir()
            model_file = model_dir / "CADCHF_model.json"
            model_file.write_text("{}")
            mhm.MODEL_DIR = model_dir

            psi_dir = tmp_path / "live" / "psi_baseline"
            psi_dir.mkdir(parents=True)
            baseline_file = psi_dir / "CADCHF.parquet"
            baseline_file.write_text("dummy")
            old_time = time.time() - 10 * 86400
            os.utime(str(baseline_file), (old_time, old_time))

            mhm.DATA_DIR = tmp_path

            result = mhm.check_psi_baseline_staleness()
            assert len(result) == 1
            assert result[0]["asset"] == "CADCHF"
            assert result[0]["status"] == "baseline_stale"
            assert result[0]["baseline_exists"] is True
        finally:
            mhm.DATA_DIR = original_data_dir
            mhm.MODEL_DIR = original_model_dir


# ── check_inference_volume with mock state.json ─────────────────────────────


class TestCheckInferenceVolume:
    """Tests for check_inference_volume — requires a state.json file."""

    def test_no_state_json(self) -> None:
        """Missing state.json returns empty list."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = Path("/nonexistent")
            result = mhm.check_inference_volume()
            assert result == []
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_empty_state(self, tmp_path: Path) -> None:
        """state.json with no assets → empty result."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            live_dir = tmp_path / "data" / "live"
            live_dir.mkdir(parents=True)
            state_file = live_dir / "state.json"
            state_file.write_text(json.dumps({"engine": {}, "assets": {}}))
            mhm.PROJECT_ROOT = tmp_path
            result = mhm.check_inference_volume()
            assert result == []
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_single_asset(self, tmp_path: Path) -> None:
        """state.json with one asset returns correct volume."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            live_dir = tmp_path / "data" / "live"
            live_dir.mkdir(parents=True)
            state_file = live_dir / "state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "engine": {"cycles_run": 1000},
                        "assets": {"GBPUSD": {"cycles_run": 1000}},
                    }
                )
            )
            mhm.PROJECT_ROOT = tmp_path
            result = mhm.check_inference_volume(warn_threshold=50000)
            assert len(result) == 1
            assert result[0]["asset"] == "GBPUSD"
            assert result[0]["estimated_inferences"] == 1000
            assert result[0]["volume_ratio"] == 0.02
            assert result[0]["is_high_volume"] is False
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_high_volume(self, tmp_path: Path) -> None:
        """Asset exceeding warn_threshold is flagged."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            live_dir = tmp_path / "data" / "live"
            live_dir.mkdir(parents=True)
            state_file = live_dir / "state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "engine": {"cycles_run": 100000},
                        "assets": {"AUDUSD": {"cycles_run": 100000}},
                    }
                )
            )
            mhm.PROJECT_ROOT = tmp_path
            result = mhm.check_inference_volume(warn_threshold=50000)
            assert len(result) == 1
            assert result[0]["asset"] == "AUDUSD"
            assert result[0]["volume_ratio"] == 1.0  # capped
            assert result[0]["is_high_volume"] is True
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_corrupt_state_json(self, tmp_path: Path) -> None:
        """Corrupt state.json returns empty list (logged warning)."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            live_dir = tmp_path / "data" / "live"
            live_dir.mkdir(parents=True)
            state_file = live_dir / "state.json"
            state_file.write_text("not valid json")
            mhm.PROJECT_ROOT = tmp_path
            result = mhm.check_inference_volume()
            assert result == []
        finally:
            mhm.PROJECT_ROOT = original_root


# ── trigger_retrain ────────────────────────────────────────────────────────


_WINDOWS_SKIP = pytest.mark.skipif(sys.platform == "win32", reason="shell script scheduler tests not applicable on Windows")


def _make_fake_retrain_py(tmpdir: Path, exit_code: int = 0) -> Path:
    """Create a fake retrain.py at scripts/eigencapital/ in tmpdir.

    This is the Python-based retrain entry point, so no chmod is needed —
    it's invoked via ``sys.executable``.
    """
    scheduler_dir = tmpdir / "scripts" / "eigencapital"
    scheduler_dir.mkdir(parents=True, exist_ok=True)
    scheduler = scheduler_dir / "retrain.py"
    scheduler.write_text(f"import sys\nprint('done')\nsys.exit({exit_code})\n")
    return scheduler


def _make_fake_scheduler(tmpdir: Path) -> Path:
    """Create a fake retrain_scheduler.sh at scripts/ops/ in tmpdir."""
    scheduler_dir = tmpdir / "scripts" / "ops"
    scheduler_dir.mkdir(parents=True, exist_ok=True)
    scheduler = scheduler_dir / "retrain_scheduler.sh"
    scheduler.write_text("#!/usr/bin/env bash\necho done\nexit 0")
    os.chmod(str(scheduler), 0o755)
    return scheduler


def _make_fake_scheduler_failing(tmpdir: Path) -> Path:
    """Create a fake retrain_scheduler.sh that fails."""
    scheduler_dir = tmpdir / "scripts" / "ops"
    scheduler_dir.mkdir(parents=True, exist_ok=True)
    scheduler = scheduler_dir / "retrain_scheduler.sh"
    scheduler.write_text("#!/usr/bin/env bash\necho fail\nexit 1")
    os.chmod(str(scheduler), 0o755)
    return scheduler


class TestTriggerRetrain:
    """Tests for trigger_retrain — needs urgency results and scheduler script."""

    def test_no_asset_needs_retrain(self) -> None:
        """When no assets need retrain, trigger_retrain returns False."""
        from scripts.ops.model_health_monitor import trigger_retrain

        urgency_results = [
            {"asset": "A", "urgency_score": 0.1, "needs_retrain": False},
            {"asset": "B", "urgency_score": 0.1, "needs_retrain": False},
        ]
        result = trigger_retrain(urgency_results)
        assert result is False

    def test_scheduler_not_found(self) -> None:
        """When both schedulers are missing, trigger_retrain logs error and returns False."""
        import scripts.ops.model_health_monitor as mhm

        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = Path("/nonexistent")
            urgency_results = [
                {"asset": "A", "urgency_score": 0.9, "needs_retrain": True},
            ]
            result = mhm.trigger_retrain(urgency_results)
            assert result is False
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_retrain_py_subprocess_success(self, tmp_path: Path) -> None:
        """The Python retrain.py script succeeds (exit code 0)."""
        import scripts.ops.model_health_monitor as mhm

        _make_fake_retrain_py(tmp_path, exit_code=0)
        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = tmp_path
            urgency_results = [
                {"asset": "A", "urgency_score": 0.9, "needs_retrain": True},
            ]
            result = mhm.trigger_retrain(urgency_results)
            assert result is True
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_retrain_py_subprocess_failure(self, tmp_path: Path) -> None:
        """The Python retrain.py script fails (exit code != 0)."""
        import scripts.ops.model_health_monitor as mhm

        _make_fake_retrain_py(tmp_path, exit_code=1)
        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = tmp_path
            urgency_results = [
                {"asset": "A", "urgency_score": 0.9, "needs_retrain": True},
            ]
            result = mhm.trigger_retrain(urgency_results)
            assert result is False
        finally:
            mhm.PROJECT_ROOT = original_root

    def test_only_some_assets_need_retrain(self, tmp_path: Path) -> None:
        """Mixed urgency — only assets with needs_retrain=True trigger the pipeline."""
        import scripts.ops.model_health_monitor as mhm

        _make_fake_retrain_py(tmp_path)
        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = tmp_path
            urgency_results = [
                {"asset": "A", "urgency_score": 0.9, "needs_retrain": True},
                {"asset": "B", "urgency_score": 0.1, "needs_retrain": False},
            ]
            result = mhm.trigger_retrain(urgency_results)
            assert result is True
        finally:
            mhm.PROJECT_ROOT = original_root

    @_WINDOWS_SKIP
    def test_scheduler_shell_fallback_found(self, tmp_path: Path) -> None:
        """When retrain.py is missing but retrain_scheduler.sh exists, use fallback."""
        import scripts.ops.model_health_monitor as mhm

        _make_fake_scheduler(tmp_path)
        original_root = mhm.PROJECT_ROOT
        try:
            mhm.PROJECT_ROOT = tmp_path
            urgency_results = [
                {"asset": "A", "urgency_score": 0.9, "needs_retrain": True},
            ]
            result = mhm.trigger_retrain(urgency_results)
            assert result is True
        finally:
            mhm.PROJECT_ROOT = original_root


# ── CLI smoke tests (via subprocess) ───────────────────────────────────────


class TestModelHealthMonitorCLI:
    """End-to-end CLI smoke tests — invokes model_health_monitor.py via subprocess."""

    SCRIPT = "scripts/ops/model_health_monitor.py"

    @staticmethod
    def _env() -> dict[str, str]:
        """Return environment with PYTHONPATH set for the subprocess."""
        import os

        env = os.environ.copy()
        cwd = os.getcwd()
        pp = env.get("PYTHONPATH", "")
        if cwd not in pp:
            env["PYTHONPATH"] = f"{cwd}:{pp}" if pp else cwd
        return env

    def _run(self, *args: str):
        """Run model_health_monitor.py with given args and return result."""
        import subprocess

        return subprocess.run(
            ["python3", self.SCRIPT, *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=self._env(),
        )

    def test_help_flag(self) -> None:
        """--help flag prints usage and exits with code 0."""
        result = self._run("--help")
        assert result.returncode == 0
        assert "usage:" in result.stdout
        assert "--help" in result.stdout
        assert "--json" in result.stdout
        assert "--trigger" in result.stdout

    def test_json_flag_produces_valid_json(self) -> None:
        """--json flag outputs valid JSON with expected top-level keys."""
        result = self._run("--json")
        assert result.returncode == 0
        assert result.stdout, "Expected stdout output"

        import json

        data = json.loads(result.stdout)
        assert "timestamp" in data
        assert "checks" in data
        assert "urgency" in data
        assert "model_age" in data["checks"]
        assert "n_assets" in data["urgency"]
        assert isinstance(data["urgency"]["n_assets"], int)
        assert data["urgency"]["n_assets"] >= 0

    def test_trigger_no_op_when_healthy(self) -> None:
        """--trigger with default threshold should not fire when all assets are healthy."""
        result = self._run("--trigger", "--json")
        assert result.returncode == 0

        import json

        data = json.loads(result.stdout)
        # All assets have urgency ~0.1, far below 0.65 threshold
        assert data["urgency"]["n_needs_retrain"] == 0
        assert data["urgency"]["max_urgency"] < 0.65

    def test_output_flag_saves_file(self, tmp_path: Path) -> None:
        """--output flag saves the JSON report to the specified path."""
        out_path = tmp_path / "health_report.json"
        result = self._run("--json", "--output", str(out_path))
        assert result.returncode == 0
        assert out_path.exists()

        import json

        with open(out_path) as f:
            data = json.load(f)
        assert "timestamp" in data
        assert "urgency" in data

    def test_custom_max_age_flag(self) -> None:
        """--max-age flag is accepted and reflected in config."""
        result = self._run("--json", "--max-age", "90")
        assert result.returncode == 0
        import json

        data = json.loads(result.stdout)
        assert data["config"]["max_age_days"] == 90
