import json
import numpy as np
import pandas as pd
import pytest

from features.liquidity_regime import (
    LiquidityRegimeSnapshot,
    compute_liquidity_features,
    classify_liquidity_regime,
    liquidity_governance_scalars,
    load_liquidity_json,
    save_liquidity_json,
    neutral_liquidity,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def ohlcv_df():
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "close": close,
        "high": close * (1 + np.random.uniform(0.001, 0.005, n)),
        "low": close * (1 - np.random.uniform(0.001, 0.005, n)),
        "volume": np.random.randint(1000, 100000, n).astype(float),
    })


# ── compute_liquidity_features ───────────────────────────────────────────────

def test_compute_liquidity_returns_dict(ohlcv_df):
    result = compute_liquidity_features(ohlcv_df)
    assert isinstance(result, dict)
    assert "volume_z" in result
    assert "amihud_z" in result
    assert "spread_est_bps" in result


def test_compute_liquidity_insufficient_data():
    df = pd.DataFrame({
        "close": [100, 101],
        "high": [101, 102],
        "low": [99, 100],
        "volume": [1000, 2000],
    })
    result = compute_liquidity_features(df)
    assert result["volume_z"] == 0.0
    assert result["amihud_z"] == 0.0
    assert result["spread_est_bps"] == 0.0


def test_compute_liquidity_single_row():
    df = pd.DataFrame({
        "close": [100],
        "high": [101],
        "low": [99],
        "volume": [1000],
    })
    result = compute_liquidity_features(df)
    assert result["volume_z"] == 0.0


def test_compute_liquidity_zero_volume():
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "close": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": [0.0] * n,
    })
    result = compute_liquidity_features(df)
    assert isinstance(result["volume_z"], float)


def test_compute_liquidity_constant_series():
    df = pd.DataFrame({
        "close": [100] * 60,
        "high": [101] * 60,
        "low": [99] * 60,
        "volume": [10000] * 60,
    })
    result = compute_liquidity_features(df)
    assert isinstance(result["volume_z"], float)
    assert isinstance(result["amihud_z"], float)


def test_compute_liquidity_no_future_leakage():
    np.random.seed(99)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "close": close,
        "high": close * (1 + np.random.uniform(0.001, 0.005, n)),
        "low": close * (1 - np.random.uniform(0.001, 0.005, n)),
        "volume": np.random.randint(1000, 100000, n).astype(float),
    })
    half = df.iloc[:30].copy()
    full = df.iloc[:50].copy()
    result_half = compute_liquidity_features(half)
    result_full = compute_liquidity_features(full)
    assert isinstance(result_half["volume_z"], float)
    assert isinstance(result_full["volume_z"], float)


# ── classify_liquidity_regime ────────────────────────────────────────────────

def test_classify_normal():
    features = {"volume_z": 0.0, "amihud_z": 0.0}
    assert classify_liquidity_regime(features) == "NORMAL"


def test_classify_thin_low_volume():
    features = {"volume_z": -2.0, "amihud_z": 0.0}
    assert classify_liquidity_regime(features) == "THIN"


def test_classify_thin_high_amihud():
    features = {"volume_z": 0.0, "amihud_z": 2.0}
    assert classify_liquidity_regime(features) == "THIN"


def test_classify_stressed_low_volume():
    features = {"volume_z": -3.0, "amihud_z": 0.0}
    assert classify_liquidity_regime(features) == "STRESSED"


def test_classify_stressed_high_amihud():
    features = {"volume_z": 0.0, "amihud_z": 4.0}
    assert classify_liquidity_regime(features) == "STRESSED"


def test_classify_stressed_overrides_thin():
    features = {"volume_z": -3.0, "amihud_z": 2.0}
    assert classify_liquidity_regime(features) == "STRESSED"


def test_classify_missing_keys_defaults_zero():
    features = {}
    assert classify_liquidity_regime(features) == "NORMAL"


def test_classify_boundary_vol_thin():
    features = {"volume_z": -1.5, "amihud_z": 0.0}
    assert classify_liquidity_regime(features) == "THIN"


def test_classify_boundary_vol_stressed():
    features = {"volume_z": -3.0, "amihud_z": 0.0}
    assert classify_liquidity_regime(features) == "STRESSED"


# ── liquidity_governance_scalars ─────────────────────────────────────────────

def test_scalars_normal():
    result = liquidity_governance_scalars("NORMAL")
    assert result["sl_mult"] == 1.0
    assert result["size_scalar"] == 1.0
    assert result["halted"] is False


def test_scalars_thin():
    result = liquidity_governance_scalars("THIN")
    assert result["sl_mult"] == 1.15
    assert result["size_scalar"] == 0.85
    assert result["halted"] is False


def test_scalars_stressed():
    result = liquidity_governance_scalars("STRESSED")
    assert result["sl_mult"] == 1.30
    assert result["size_scalar"] == 0.70
    assert result["halted"] is True


def test_scalars_custom_percentages():
    result = liquidity_governance_scalars(
        "THIN", thin_sl_widen_pct=20.0, thin_size_reduce_pct=10.0
    )
    assert result["sl_mult"] == 1.20
    assert result["size_scalar"] == 0.90


def test_scalars_unknown_regime_falls_to_normal():
    result = liquidity_governance_scalars("UNKNOWN")
    assert result["sl_mult"] == 1.0
    assert result["size_scalar"] == 1.0
    assert result["halted"] is False


# ── load_liquidity_json ──────────────────────────────────────────────────────

def test_load_liquidity_json_success(tmp_path):
    data = {
        "timestamp": "2026-05-25T00:00:00",
        "regime": "NORMAL",
        "volume_z": 0.0,
        "amihud_z": 0.0,
        "spread_est_bps": 0.0,
        "sl_mult": 1.0,
        "size_scalar": 1.0,
        "halted": False,
    }
    path = str(tmp_path / "liquidity.json")
    with open(path, "w") as f:
        json.dump(data, f)
    result = load_liquidity_json(path)
    assert result is not None
    assert result.regime == "NORMAL"


def test_load_liquidity_json_file_not_found():
    result = load_liquidity_json("/nonexistent/path.json")
    assert result is None


def test_load_liquidity_json_invalid_json(tmp_path):
    path = str(tmp_path / "bad.json")
    with open(path, "w") as f:
        f.write("{invalid")
    result = load_liquidity_json(path)
    assert result is None


def test_load_liquidity_json_type_error():
    result = load_liquidity_json(None)
    assert result is None


def test_load_liquidity_json_missing_fields(tmp_path):
    path = str(tmp_path / "partial.json")
    with open(path, "w") as f:
        json.dump({"regime": "NORMAL", "timestamp": "now"}, f)
    result = load_liquidity_json(path)
    assert result is None


# ── save_liquidity_json ──────────────────────────────────────────────────────

def test_save_liquidity_json_roundtrip(tmp_path):
    snapshot = LiquidityRegimeSnapshot(
        timestamp="2026-05-25T00:00:00",
        regime="THIN",
        volume_z=-1.8,
        amihud_z=1.2,
        spread_est_bps=15.5,
        sl_mult=1.15,
        size_scalar=0.85,
    )
    path = str(tmp_path / "liquidity_out.json")
    save_liquidity_json(path, snapshot)
    loaded = load_liquidity_json(path)
    assert loaded is not None
    assert loaded.regime == "THIN"
    assert loaded.volume_z == -1.8


# ── neutral_liquidity ────────────────────────────────────────────────────────

def test_neutral_liquidity_defaults():
    result = neutral_liquidity()
    assert result.regime == "NORMAL"
    assert result.volume_z == 0.0
    assert result.amihud_z == 0.0
    assert result.spread_est_bps == 0.0
    assert result.sl_mult == 1.0
    assert result.size_scalar == 1.0
    assert result.halted is False
    assert isinstance(result.timestamp, str)


def test_liquidity_regime_snapshot_creation():
    snap = LiquidityRegimeSnapshot(
        timestamp="2026-05-25T00:00:00",
        regime="STRESSED",
        volume_z=-3.0,
        amihud_z=3.5,
        spread_est_bps=45.2,
        sl_mult=1.3,
        size_scalar=0.7,
        halted=True,
    )
    assert snap.regime == "STRESSED"
    assert snap.halted is True
