import pandas as pd

from features.lead_lag_features import (
    load_lead_lag_edges,
    apply_lead_lag_features,
    DEFAULT_LEAD_LAG_EDGES,
    DEFAULT_EDGES_PATH,
)


# ── load_lead_lag_edges ──────────────────────────────────────────────────────

def test_load_lead_lag_edges_default_when_no_file():
    """Returns DEFAULT_LEAD_LAG_EDGES when no file exists."""
    edges = load_lead_lag_edges(path="/nonexistent/path.yaml")
    assert edges == DEFAULT_LEAD_LAG_EDGES


def test_load_lead_lag_edges_with_valid_file(tmp_path):
    """Loads edges from a valid YAML file."""
    import yaml
    path = tmp_path / "edges.yaml"
    data = {"edges": [{"target": "EURUSD", "leader": "DXY", "lag": 1, "column": "dxy_lead_1"}]}
    with open(path, "w") as f:
        yaml.dump(data, f)
    edges = load_lead_lag_edges(path=str(path))
    assert len(edges) == 1
    assert edges[0]["target"] == "EURUSD"


def test_load_lead_lag_edges_empty_file(tmp_path):
    """Returns DEFAULT_LEAD_LAG_EDGES when file has no edges key."""
    import yaml
    path = tmp_path / "edges_empty.yaml"
    with open(path, "w") as f:
        yaml.dump({}, f)
    edges = load_lead_lag_edges(path=str(path))
    assert edges == DEFAULT_LEAD_LAG_EDGES


# ── apply_lead_lag_features ──────────────────────────────────────────────────

def test_apply_lead_lag_features_returns_series():
    """Returns a pandas Series with renamed column."""
    target = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
    leader = pd.DataFrame({"close": [200, 202, 201, 205, 208]})
    result = apply_lead_lag_features(target, leader, lag=1, column_name="lead_test")
    assert isinstance(result, pd.Series)
    assert result.name == "lead_test"


def test_apply_lead_lag_features_shifts_returns():
    """Returns are shifted by the specified lag."""
    target = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
    leader = pd.DataFrame({"close": [200, 205, 210, 215, 220]})
    result = apply_lead_lag_features(target, leader, lag=1, column_name="lead_test")
    expected = leader["close"].pct_change().shift(1)
    pd.testing.assert_series_equal(result, expected.rename("lead_test"))


def test_apply_lead_lag_features_lag_zero():
    """Lag of 0 returns contemporaneous returns."""
    target = pd.DataFrame({"close": [100, 101, 102]})
    leader = pd.DataFrame({"close": [200, 210, 200]})
    result = apply_lead_lag_features(target, leader, lag=0, column_name="lag0")
    expected = leader["close"].pct_change().shift(0)
    pd.testing.assert_series_equal(result, expected.rename("lag0"))


def test_default_edges_have_required_keys():
    """All default edges have target, leader, lag, column keys."""
    for edge in DEFAULT_LEAD_LAG_EDGES:
        assert "target" in edge
        assert "leader" in edge
        assert "lag" in edge
        assert "column" in edge


def test_default_edges_lag_is_positive():
    for edge in DEFAULT_LEAD_LAG_EDGES:
        assert edge["lag"] >= 0


def test_default_edges_path_constant():
    assert DEFAULT_EDGES_PATH.endswith("lead_lag_edges.yaml")
