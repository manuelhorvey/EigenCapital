import pytest

from backtests.model_evolution import (
    append_trajectory,
    compute_convergence,
    compute_mas_acceleration,
    compute_mas_velocity,
    compute_subaxis_drift,
    estimate_equilibrium_band,
    load_all_trajectories,
    load_trajectory,
)


class TestComputeMasVelocity:
    def test_empty_trajectory(self):
        assert compute_mas_velocity([]) == []

    def test_single_entry(self):
        traj = [{"mas": 80.0}]
        assert compute_mas_velocity(traj) == []

    def test_two_entries(self):
        traj = [{"mas": 70.0}, {"mas": 80.0}]
        vel = compute_mas_velocity(traj)
        assert vel == [10.0]

    def test_multiple_entries_without_window(self):
        traj = [{"mas": 70.0}, {"mas": 80.0}, {"mas": 75.0}]
        vel = compute_mas_velocity(traj, window=None)
        assert vel == [10.0, -5.0]

    def test_smoothed_with_window(self):
        traj = [{"mas": 60.0}, {"mas": 70.0}, {"mas": 80.0}, {"mas": 75.0}, {"mas": 85.0}]
        vel = compute_mas_velocity(traj, window=3)
        assert len(vel) == 4
        # velocities = [10, 10, -5, 10]
        # smoothed:
        # i=0: lo=0 -> avg(10) = 10
        # i=1: lo=0 -> avg(10,10) = 10
        # i=2: lo=0 -> avg(10,10,-5) = 5.0
        # i=3: lo=1 -> avg(10,-5,10) = 5.0
        assert vel == pytest.approx([10.0, 10.0, 5.0, 5.0])


class TestComputeMasAcceleration:
    def test_empty_trajectory(self):
        assert compute_mas_acceleration([]) == []

    def test_single_entry(self):
        assert compute_mas_acceleration([{"mas": 80.0}]) == []

    def test_two_entries(self):
        # Only 1 velocity from 2 entries -> cannot compute acceleration
        acc = compute_mas_acceleration([{"mas": 70.0}, {"mas": 80.0}])
        assert acc == []

    def test_multiple(self):
        traj = [{"mas": 60.0}, {"mas": 70.0}, {"mas": 80.0}, {"mas": 75.0}]
        # velocities = [10, 10, -5] -> accelerations = [0, -15]
        acc = compute_mas_acceleration(traj, window=None)
        assert acc == [0.0, -15.0]


class TestComputeSubaxisDrift:
    def test_empty_trajectory(self):
        assert compute_subaxis_drift([]) == {}

    def test_single_entry(self):
        traj = [{"sub_scores": {"model": 0.5, "signal": 0.6}}]
        assert compute_subaxis_drift(traj) == {}

    def test_drift_computation(self):
        traj = [
            {"sub_scores": {"model": 0.5, "signal": 0.6}},
            {"sub_scores": {"model": 0.7, "signal": 0.8}},
            {"sub_scores": {"model": 0.9, "signal": 0.4}},
        ]
        drift = compute_subaxis_drift(traj, window=2)
        assert drift["model"] == pytest.approx(0.9 - 0.7, abs=1e-4)
        assert drift["signal"] == pytest.approx(0.4 - 0.8, abs=1e-4)

    def test_drift_with_large_window(self):
        traj = [
            {"sub_scores": {"model": 0.5}},
            {"sub_scores": {"model": 0.7}},
            {"sub_scores": {"model": 0.9}},
        ]
        drift = compute_subaxis_drift(traj, window=10)
        assert drift["model"] == pytest.approx(0.9 - 0.5, abs=1e-4)


class TestComputeConvergence:
    def test_empty_trajectories(self):
        result = compute_convergence({})
        assert result["current_variance"] == 0.0
        assert result["current_mean"] == 0.0
        assert result["convergence_direction"] == "insufficient_data"

    def test_single_asset(self):
        result = compute_convergence({"EURUSD": [{"mas": 80.0}]})
        # Needs >= 2 assets for mean/variance; < 2 returns zeros
        assert result["current_mean"] == 0.0
        assert result["current_variance"] == 0.0
        assert result["convergence_direction"] == "insufficient_data"

    def test_two_assets(self):
        result = compute_convergence(
            {
                "EURUSD": [{"mas": 80.0}],
                "GBPUSD": [{"mas": 70.0}],
            }
        )
        assert result["current_mean"] == 75.0
        assert result["current_variance"] > 0
        assert "asset_spread" in result
        assert result["asset_spread"]["EURUSD"] == 5.0
        assert result["asset_spread"]["GBPUSD"] == -5.0

    def test_convergence_timeline(self):
        result = compute_convergence(
            {
                "EURUSD": [{"mas": 80.0}, {"mas": 85.0}],
                "GBPUSD": [{"mas": 70.0}, {"mas": 75.0}],
            }
        )
        assert "variance_timeline" in result
        assert len(result["variance_timeline"]) >= 1

    def test_diverging_detection(self):
        result = compute_convergence(
            {
                "EURUSD": [{"mas": 80.0}, {"mas": 85.0}],
                "GBPUSD": [{"mas": 70.0}, {"mas": 65.0}],
            }
        )
        assert result["convergence_direction"] in ("converging", "diverging", "stable")


class TestEstimateEquilibriumBand:
    def test_insufficient_data(self):
        assert estimate_equilibrium_band([], window=10)["stable"] is False
        assert estimate_equilibrium_band([{"mas": 80.0}], window=10)["stable"] is False
        assert estimate_equilibrium_band([{"mas": 80.0}, {"mas": 81.0}], window=10)["stable"] is False

    def test_sufficient_data(self):
        traj = [{"mas": 80.0}] * 10
        band = estimate_equilibrium_band(traj, window=5)
        assert band["mean"] == 80.0
        assert band["std"] == 0.0
        assert band["stable"]

    def test_variable_data(self):
        traj = [{"mas": float(v)} for v in [75, 78, 80, 82, 85, 83, 81, 79, 77, 76]]
        band = estimate_equilibrium_band(traj, window=5)
        assert band["mean"] is not None
        assert band["std"] > 0


class TestAppendAndLoadTrajectory:
    def test_append_and_load(self, tmp_path):
        asset = "test_asset"
        evo_dir = tmp_path / "sandbox" / "evolution"

        import backtests.model_evolution as me

        orig_evolution_dir = me.EVOLUTION_DIR

        try:
            me.EVOLUTION_DIR = str(evo_dir)
            entry = append_trajectory(
                asset=asset,
                mas=85.5,
                delta_mas=5.5,
                decision="ACCEPT",
                sub_scores={"model": 0.8, "signal": 0.7},
                forward_result={
                    "baseline": {"sharpe": 1.0, "hit_rate": 0.3, "stability": 0.8},
                    "new": {"sharpe": 1.2, "hit_rate": 0.35, "stability": 0.85},
                },
            )
            assert entry["mas"] == 85.5
            assert entry["decision"] == "ACCEPT"

            loaded = load_trajectory(asset)
            assert len(loaded) == 1
            assert loaded[0]["mas"] == 85.5

            append_trajectory(
                asset=asset,
                mas=88.0,
                delta_mas=2.5,
                decision="ACCEPT",
                sub_scores={},
                forward_result={},
            )
            loaded = load_trajectory(asset)
            assert len(loaded) == 2

            loaded_limited = load_trajectory(asset, max_entries=1)
            assert len(loaded_limited) == 1
        finally:
            me.EVOLUTION_DIR = orig_evolution_dir

    def test_load_missing_asset(self):
        import backtests.model_evolution as me

        orig = me.EVOLUTION_DIR
        try:
            me.EVOLUTION_DIR = "/tmp/nonexistent_evo"
            assert load_trajectory("missing") == []
        finally:
            me.EVOLUTION_DIR = orig

    def test_load_all_trajectories(self, tmp_path):
        import backtests.model_evolution as me

        orig = me.EVOLUTION_DIR
        try:
            me.EVOLUTION_DIR = str(tmp_path / "sandbox" / "evolution")
            append_trajectory("asset1", 80.0, 0.0, "SHADOW_ONLY", {}, {})
            append_trajectory("asset2", 90.0, 5.0, "ACCEPT", {}, {})
            all_t = load_all_trajectories()
            assert "asset1" in all_t
            assert "asset2" in all_t
            assert len(all_t["asset1"]) == 1
        finally:
            me.EVOLUTION_DIR = orig

    def test_load_all_empty_dir(self, tmp_path):
        import backtests.model_evolution as me

        orig = me.EVOLUTION_DIR
        try:
            me.EVOLUTION_DIR = str(tmp_path / "empty_evo")
            assert load_all_trajectories() == {}
        finally:
            me.EVOLUTION_DIR = orig
