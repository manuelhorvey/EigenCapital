"""Path-table deliverables: grouping, matrix, cost, survival contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.volatility import config as C
from research.volatility import evidence as E
from research.volatility import path_tables as PT


def _frame(n: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    assets = np.array(["EURUSD", "GBPJPY", "XAUUSD"])
    regimes = np.array(["LOW", "NORMAL", "HIGH"])
    return pd.DataFrame(
        {
            "asset": rng.choice(assets, n),
            "entry_regime": rng.choice(regimes, n),
            "entry_regime_z": rng.choice(regimes, n),
            "holding_bars": rng.choice([5, 6, 7], n),
            "first_profit_bar": rng.choice([1, 2, 3, np.nan], n, p=[0.4, 0.3, 0.2, 0.1]),
            "time_to_mae": rng.integers(1, 6, n).astype(float),
            "time_to_mfe": rng.integers(1, 6, n).astype(float),
            "max_underwater_run": rng.integers(0, 5, n).astype(float),
            "max_underwater_run_net": rng.integers(0, 5, n).astype(float),
            "underwater_fraction": rng.uniform(0, 1, n),
            "underwater_fraction_net": rng.uniform(0, 1, n),
            "mae_ret": rng.uniform(0.001, 0.02, n),
            "mae_sigma": rng.uniform(0.5, 3, n),
            "mfe_ret": rng.uniform(0.001, 0.03, n),
            "mfe_sigma": rng.uniform(0.5, 3, n),
            "crossings_per_bar": rng.uniform(0, 0.5, n),
            "entry_crossings": rng.integers(0, 5, n).astype(float),
            "path_efficiency": rng.uniform(0, 1, n),
            "net_pnl": rng.normal(0, 0.001, n),
            "gross_pnl": rng.normal(0, 0.0015, n),
            "costs": np.full(n, 2 * C.R4_COST_ONE_WAY * 0.1),
            "entry_weight": np.full(n, 0.1),
            "exit_u_ret": rng.normal(0, 0.01, n),
            "trade_type": rng.choice(["A_immediate_directional", "D_persistent_adverse"], n),
            "side": rng.choice(["LONG", "SHORT"], n),
            "entry_rv_pctile": rng.uniform(0, 1, n),
        }
    )


def test_per_asset_table_gates_insufficient():
    f = _frame()
    # force one asset below MIN_CELL_TRADES
    tiny_idx = f.index[f["asset"] == "XAUUSD"][: C.MIN_CELL_TRADES - 5]
    f.loc[tiny_idx, "asset"] = "TINY"
    # drop remaining XAU rows so TINY stays small
    f = f[f["asset"] != "XAUUSD"]
    out = PT.per_asset_trade_path_table(f)
    assert "TINY" in out
    assert out["TINY"]["verdict"] == E.INSUFFICIENT_DATA
    assert "EURUSD" in out
    assert out["EURUSD"]["n_trades"] >= C.MIN_CELL_TRADES


def test_per_asset_regime_cells_gate():
    out = PT.per_asset_regime_table(_frame())
    assert "percentile_pit" in out and "zscore" in out
    cells = out["percentile_pit"]["EURUSD"]
    for reg in C.REGIME_LABELS:
        assert reg in cells
        if cells[reg].get("verdict") == E.INSUFFICIENT_DATA:
            assert cells[reg]["n"] < C.MIN_CELL_TRADES


def test_vol_path_matrix_shapes():
    out = PT.volatility_trade_path_matrix(_frame())
    assert out["thresholds"]["fast_le"] == 1.0
    assert out["thresholds"]["moderate_le"] == 3.0
    assert set(out["by_regime"]) <= set(C.REGIME_LABELS) | {"n"}
    for reg, cell in out["by_regime"].items():
        if "verdict" in cell:
            continue
        assert cell["n"] >= C.MIN_CELL_TRADES
        assert set(cell["shares"]) == {"fast", "moderate", "slow", "no_profit"}
        assert sum(cell["shares"].values()) == pytest.approx(1.0, abs=1e-9)


def test_cost_analysis_runs_and_counts():
    before = E.LEDGER.comparisons.get("cost_analysis:per_asset", 0)
    out = PT.cost_analysis(_frame())
    assert "by_asset" in out and "by_entry_regime" in out
    after = E.LEDGER.comparisons.get("cost_analysis:per_asset", 0)
    assert after > before


def test_survival_censor_rate():
    f = _frame()
    out = PT.survival_time_to_event(f)
    fp = out["first_profit"]
    assert fp["n"] + fp["n_censored_no_profit"] == len(f)
    assert 0.0 <= fp["censor_rate"] <= 1.0
    assert fp["n_censored_no_profit"] > 0  # synthetic has NaNs


def test_cluster_path_link_and_nn():
    labels = {"EURUSD": 1, "GBPJPY": 1, "XAUUSD": 2}
    out = PT.cluster_path_link(_frame(n=200), labels)
    assert "by_cluster" in out
    assert "trade_path_nearest_neighbor" in out
    nn = out["trade_path_nearest_neighbor"]
    assert set(nn) == {"EURUSD", "GBPJPY", "XAUUSD"}
    for v in nn.values():
        assert v["nearest"] in nn
        assert v["nearest"] is not None
        assert v["distance"] >= 0


def test_holding_bucket_h1_recorded():
    out = PT.holding_period_buckets(_frame(n=200))
    assert set(out) <= {"short", "medium", "long"}
    # modal synthetic holding is 6 → medium
    assert "medium" in out
    if "h1_rho_within_bucket" in out.get("medium", {}):
        rho = out["medium"]["h1_rho_within_bucket"]["rho"]
        assert rho is None or np.isnan(rho) or -1.0 <= rho <= 1.0


def test_build_all_keys():
    labels = {"EURUSD": 1, "GBPJPY": 1, "XAUUSD": 2}
    out = PT.build_all_path_tables(_frame(), labels)
    for k in (
        "per_asset_trade_path",
        "per_asset_regime",
        "volatility_trade_path_matrix",
        "cost_analysis",
        "survival_time_to_event",
        "cluster_path_link",
        "holding_period_control",
    ):
        assert k in out
