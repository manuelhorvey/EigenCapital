"""Unit tests for monitor_paper_trading calibration monitoring."""

from scripts.ops.monitor_paper_trading import check_calibration


def test_empty_state_returns_empty():
    assert check_calibration({}) == []


def test_no_assets_returns_empty():
    assert check_calibration({"assets": {}}) == []


def test_watch_asset_below_min_trades():
    state = {"assets": {"NZDCAD": {"metrics": {"n_trades": 5, "mean_confidence": 90, "win_rate": 50}}}}
    assert check_calibration(state) == []


def test_nzdcad_alert_overconfident():
    state = {"assets": {"NZDCAD": {"metrics": {"n_trades": 25, "mean_confidence": 85, "win_rate": 60}}}}
    msgs = check_calibration(state)
    assert len(msgs) == 1
    assert "CALIBRATION ALERT" in msgs[0]
    assert "NZDCAD" in msgs[0]
    assert "gap=25pp" in msgs[0]


def test_nzdusd_watch_borderline():
    state = {"assets": {"NZDUSD": {"metrics": {"n_trades": 22, "mean_confidence": 72, "win_rate": 60}}}}
    msgs = check_calibration(state)
    assert len(msgs) == 1
    assert "CALIBRATION WATCH" in msgs[0]
    assert "NZDUSD" in msgs[0]
    assert "gap=12pp" in msgs[0]


def test_nzdcad_ok():
    state = {"assets": {"NZDCAD": {"metrics": {"n_trades": 30, "mean_confidence": 65, "win_rate": 62}}}}
    msgs = check_calibration(state)
    assert len(msgs) == 1
    assert "CALIBRATION OK" in msgs[0]
    assert "NZDCAD" in msgs[0]
    assert "gap=3pp" in msgs[0]


def test_both_assets_with_trades():
    state = {
        "assets": {
            "NZDCAD": {"metrics": {"n_trades": 20, "mean_confidence": 80, "win_rate": 55}},
            "NZDUSD": {"metrics": {"n_trades": 25, "mean_confidence": 62, "win_rate": 58}},
        }
    }
    msgs = check_calibration(state)
    assert len(msgs) == 2
    assert any("CALIBRATION ALERT" in m for m in msgs)
    assert any("CALIBRATION OK" in m for m in msgs)


def test_missing_metrics_graceful():
    state = {"assets": {"NZDCAD": {"metrics": {"n_trades": 20}}}}
    msgs = check_calibration(state)
    assert len(msgs) == 1
    assert "CALIBRATION OK" in msgs[0]


def test_non_watch_asset_ignored():
    state = {"assets": {"EURUSD": {"metrics": {"n_trades": 100, "mean_confidence": 95, "win_rate": 30}}}}
    assert check_calibration(state) == []
