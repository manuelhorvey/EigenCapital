import pandas as pd
import pytest

from research.lead_lag.lead_lag_matrix import build_lead_lag_matrix, plot_lead_lag_heatmap


def test_build_lead_lag_matrix_shape():
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    s1 = pd.Series([0.01, -0.01, 0.02, -0.02] * 50, index=idx)
    s2 = s1.shift(2).fillna(0)
    matrix = build_lead_lag_matrix({"A": s1, "B": s2}, max_lag=5)
    assert matrix.shape == (2, 2)
    assert matrix.loc["A", "A"] == 0


def test_plot_heatmap_optional(tmp_path):
    matrix = pd.DataFrame([[0, 2], [-1, 0]], index=["A", "B"], columns=["A", "B"])
    out = tmp_path / "heatmap.png"
    result = plot_lead_lag_heatmap(matrix, str(out))
    if result is not None:
        assert out.exists()
