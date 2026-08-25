"""Phase 1U item 1 — concentration & asset-class caps enforcement."""

from eigencapital.risk.checks.account_checks import (
    AccountState,
    check_asset_class_exposure,
    check_max_concentration,
    run_all_account_checks,
)
from eigencapital.risk.policy import RiskPolicy


def _state(inst=None, cls=None) -> AccountState:
    return AccountState(equity=100_000.0, peak_equity=100_000.0,
                        instrument_exposures=inst or {},
                        asset_class_exposures=cls or {})


class TestMaxConcentration:
    def test_pass_below_warn(self):
        r = check_max_concentration(_state({"EURUSDm": 10_000}), RiskPolicy())
        assert r.status == "PASS"

    def test_warn_between_thresholds(self):
        r = check_max_concentration(_state({"EURUSDm": 20_000}), RiskPolicy())
        assert r.status == "WARN"
        assert "elevated" in r.message

    def test_fail_above_cap(self):
        r = check_max_concentration(_state({"XAUUSDm": 30_000}), RiskPolicy())
        assert r.status == "FAIL"
        assert "XAUUSDm" in r.message

    def test_negative_notional_uses_abs(self):
        r = check_max_concentration(_state({"BTCUSDm": -40_000}), RiskPolicy())
        assert r.status == "FAIL"

    def test_empty_passes(self):
        assert check_max_concentration(_state(), RiskPolicy()).status == "PASS"


class TestAssetClassExposure:
    def test_fail_above_cap(self):
        st = _state(cls={"crypto": 45_000})
        r = check_asset_class_exposure(st, RiskPolicy())
        assert r.status == "FAIL" and "crypto" in r.message

    def test_pass_within_cap(self):
        r = check_asset_class_exposure(
            _state(cls={"forex": 20_000, "indices": 15_000}), RiskPolicy())
        assert r.status == "PASS"

    def test_empty_passes(self):
        assert check_asset_class_exposure(_state(), RiskPolicy()).status == "PASS"


class TestPipelineIntegration:
    def test_both_checks_run_in_pipeline(self):
        results = run_all_account_checks(
            _state({"XAUUSDm": 50_000}, {"metals": 50_000}), RiskPolicy())
        ids = {r.check_id for r in results}
        assert {"max_concentration", "asset_class_exposure"} <= ids
        by_id = {r.check_id: r for r in results}
        assert by_id["max_concentration"].status == "FAIL"
        assert by_id["asset_class_exposure"].status == "FAIL"

    def test_clean_state_all_pass(self):
        results = run_all_account_checks(_state({}, {}), RiskPolicy())
        assert all(r.status != "FAIL" for r in results)
