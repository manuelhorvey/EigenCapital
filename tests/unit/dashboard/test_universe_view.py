"""Universe-view tests — dashboard derives the production universe from config.

Contract: docs/production/DASHBOARD_CONTRACT.md §6 (production universe
adjudication) + docs/production/HK50_JP225_UNIVERSE_ADMISSION.md.

The dashboard must be a *window* into the authoritative universe
(`configs/production/config.toml` → `[broker.allowed_symbols]`), never a
second source of truth, and must never render unknown data as a value it
does not have (no fabricated bars, no fabricated zeroes).
"""

from __future__ import annotations

import pytest

from eigencapital.dashboard.services.dashboard_state import DashboardStateService


@pytest.fixture
def service() -> DashboardStateService:
    """Service with no local reports — config is the only universe source."""
    return DashboardStateService()


class TestConfigDerivedUniverse:
    """_build_universe_view must be driven by the production config."""

    def test_hk50_jp225_present_and_admitted(self, service: DashboardStateService) -> None:
        """HK50/JP225 (admitted 2026-09-27) must render as eligible indices."""
        rows = {r["symbol"]: r for r in service._build_universe_view({})}
        for sym in ("HK50", "JP225"):
            assert sym in rows, f"{sym} missing from dashboard universe view"
            assert rows[sym]["asset_class"] == "indices"
            assert rows[sym]["in_production_universe"] is True
            assert rows[sym]["exclusion_reason"] is None

    def test_missing_local_data_is_not_fabricated(self, service: DashboardStateService) -> None:
        """No CSV → NO_LOCAL_DATA with null newest_bar/age. Never 'OK', never 0."""
        rows = {r["symbol"]: r for r in service._build_universe_view({})}
        for sym in ("HK50", "JP225"):
            assert rows[sym]["data_status"] == "NO_LOCAL_DATA"
            assert rows[sym]["newest_bar"] is None
            assert rows[sym]["age_days"] is None
            assert rows[sym]["sources"] == []

    def test_forex_excluded_still_marked_ineligible(self, service: DashboardStateService) -> None:
        """Admission did not move any forex_excluded symbol into eligibility."""
        rows = {r["symbol"]: r for r in service._build_universe_view({})}
        excluded = [r for r in rows.values() if r["asset_class"] == "forex_excluded"]
        assert len(excluded) == 7, f"expected 7 forex_excluded, got {len(excluded)}"
        for row in excluded:
            assert row["in_production_universe"] is False
            assert row["exclusion_reason"] is not None
        assert "HK50" not in {r["symbol"] for r in excluded}
        assert "JP225" not in {r["symbol"] for r in excluded}

    def test_observed_bars_overlay_config_rows(self, service: DashboardStateService) -> None:
        """Observed CSV freshness merges onto the config row for the symbol."""
        observation = [
            {
                "symbol": "HK50",
                "source": "data/mt5",
                "asset_class": None,
                "newest_bar": "2026-09-26T00:00:00+00:00",
                "age_days": 1,
                "status": "OK",
            }
        ]
        rows = {r["symbol"]: r for r in service._build_universe_view({"HK50": observation})}
        assert rows["HK50"]["data_status"] == "OK"
        assert rows["HK50"]["newest_bar"] == "2026-09-26T00:00:00+00:00"
        assert rows["HK50"]["in_production_universe"] is True
        # JP225 has no data — still truthful about it
        assert rows["JP225"]["data_status"] == "NO_LOCAL_DATA"

    def test_symbols_without_config_are_non_production(self, service: DashboardStateService) -> None:
        """CSV for a symbol outside the config stays flagged research-only."""
        observation = [
            {
                "symbol": "N225",
                "source": "data/taxonomy_d1",
                "asset_class": None,
                "newest_bar": "2026-09-26T00:00:00+00:00",
                "age_days": 1,
                "status": "OK",
            }
        ]
        rows = {r["symbol"]: r for r in service._build_universe_view({"N225": observation})}
        assert rows["N225"]["in_production_universe"] is False
        assert "not in production config" in str(rows["N225"]["exclusion_reason"])
