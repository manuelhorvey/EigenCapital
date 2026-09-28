"""M-8 — Dashboard masks raw financial data on the broad streaming surface.

FINDINGS.md M-8 (MEDIUM): "Dashboard exposes raw financial data without
masking" — `dashboard/src/`.

Human decision (followed exactly): mask in the DTO layer — masked account IDs
(keep at most the last four characters), rounded balances/notionals, truncated
names; exact values stay available only behind the authenticated API.

Covered here:
1. The mask helpers themselves (account ID, balance/notional, name).
2. The streaming DTO (`get_live_state` — one snapshot shared by the
   `/ws/live` broadcast and `/api/v1/events/stream`) contains NO raw account
   id / balance.
3. The authenticated REST endpoints (`X-API-Key`, H-11) still return exact
   values for legitimate dashboard use, and the API-key check is still on.
4. Client-side static checks on `dashboard/src/**` (the dashboard has no JS
   test runner — L-6 — so the frontend is checked from this suite).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Raw fixtures — deliberately non-round so a masked value can never coincide.
RAW_ACCOUNT_ID = "436921728"
RAW_ACCOUNT_NAME = "EigenCapital-R4-Trial-Account-Name-That-Is-Long"
RAW_BALANCE = 10432.57
RAW_EQUITY = 12345.67
RAW_ENTRY_PRICE = 2500.123

API_KEY = "test-key-m8"


def _raw_account_state() -> dict[str, Any]:
    """Shape of `DashboardStateService.get_account_state()` plus id/name."""
    return {
        "account_id": RAW_ACCOUNT_ID,
        "account_name": RAW_ACCOUNT_NAME,
        "equity": RAW_EQUITY,
        "balance": RAW_BALANCE,
        "free_margin": 9876.54,
        "margin_used": 1234.56,
        "margin_utilization": 0.1234,
        "equity_high_water": 12400.11,
        "drawdown": 54.44,
        "drawdown_pct": 0.0044,
        "daily_pnl": 123.45,
        "daily_loss_remaining": 200.67,
        "unrealized_pnl": -89.12,
        "currency": "USD",
        "timestamp": datetime.now(UTC).isoformat(),
        "freshness": "LIVE",
        "source": "mt5",
    }


def _raw_positions() -> list[dict[str, Any]]:
    return [
        {
            "ticket": 777001,
            "symbol": "XAUUSD",
            "direction": "BUY",
            "size": 0.1,
            "entry_price": RAW_ENTRY_PRICE,
            "current_price": 2510.456,
            "unrealized_pnl": 10.55,
            "unrealized_pnl_pct": 0.0042,
            "stop_loss": 2480.5,
            "distance_to_sl": 19.62,
            "mae": -0.0021,
            "mfe": 0.0044,
            "holding_time": "12m",
            "risk_state": "NORMAL",
            "protected": True,
            "attribution_state": None,
            "last_update": datetime.now(UTC).isoformat(),
            "freshness": "LIVE",
            "source": "mt5",
        }
    ]


class _FakeStateService:
    """Read-only stand-in for DashboardStateService with raw values."""

    def get_account_state(self) -> dict[str, Any]:
        return _raw_account_state()

    def get_positions(self) -> list[dict[str, Any]]:
        return _raw_positions()

    def get_system_health(self) -> dict[str, Any]:
        return {
            "overall_state": "HEALTHY",
            "trading_authorization": "TRADING_AUTHORIZED",
            "dimensions": [],
            "blocking_dimensions": [],
            "timestamp": datetime.now(UTC).isoformat(),
            "freshness": "LIVE",
        }

    def get_risk_state(self) -> dict[str, Any]:
        return {
            "overall_level": "NORMAL",
            "observations": [
                {
                    "dimension": "daily_loss",
                    "level": "NORMAL",
                    "value": 123.45,
                    "limit": 250.67,
                    "message": "Daily loss within budget",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "details": {},
                }
            ],
            "any_critical": False,
            "any_warning": False,
            "critical_dimensions": [],
            "warning_dimensions": [],
            "timestamp": datetime.now(UTC).isoformat(),
            "freshness": "LIVE",
        }

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "alert_id": "alert-1",
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": "WARNING",
                "category": "RISK",
                "message": "Balance drawdown warning for account",
                "details": {"balance": RAW_BALANCE},
                "acknowledged": False,
            }
        ]


# ═══════════════════════════════════════════════════════════════════
# 1 — Mask helpers (DTO layer)
# ═══════════════════════════════════════════════════════════════════


class TestMaskHelpers:
    """Account IDs → last 4 only; amounts → rounded; names → truncated."""

    def test_account_id_keeps_last_four_only(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_account_id

        masked = mask_account_id(RAW_ACCOUNT_ID)
        assert isinstance(masked, str)
        assert masked.endswith(RAW_ACCOUNT_ID[-4:])
        assert RAW_ACCOUNT_ID not in masked

    def test_short_account_id_is_fully_masked(self) -> None:
        """A four-character ID must not survive as-is (\"keep last 4 at most\")."""
        from eigencapital.dashboard.schemas.masking import mask_account_id

        masked = mask_account_id("1234")
        assert masked != "1234"
        assert len(masked) == 4

    def test_balance_is_rounded_to_three_significant_figures(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_amount

        masked = mask_amount(RAW_BALANCE)
        assert masked != RAW_BALANCE
        assert str(RAW_BALANCE) not in str(masked)
        assert float(masked) == pytest.approx(10400.0)

    def test_notional_sized_amount_is_rounded(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_amount

        masked = mask_amount(RAW_EQUITY)
        assert masked != RAW_EQUITY
        assert str(RAW_EQUITY) not in str(masked)

    def test_integer_amounts_stay_integral(self) -> None:
        """Masking must not change the DTO field type (int stays int)."""
        from eigencapital.dashboard.schemas.masking import mask_amount

        assert isinstance(mask_amount(10000), int)
        assert isinstance(mask_amount(RAW_BALANCE), float)

    def test_long_name_is_truncated(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_name

        masked = mask_name(RAW_ACCOUNT_NAME)
        assert isinstance(masked, str)
        assert len(masked) <= 33  # 32 chars + ellipsis
        assert masked != RAW_ACCOUNT_NAME

    def test_short_name_is_untouched(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_name

        assert mask_name("R4") == "R4"

    def test_ratios_and_counts_are_not_rounded_as_money(self) -> None:
        """`*_pct` / `*_utilization` are ratios — masking must not distort them."""
        from eigencapital.dashboard.schemas.masking import mask_dto

        masked = mask_dto({"drawdown_pct": 0.0044, "margin_utilization": 0.1234})
        assert masked["drawdown_pct"] == 0.0044
        assert masked["margin_utilization"] == 0.1234

    def test_mask_dto_hides_nested_raw_values(self) -> None:
        from eigencapital.dashboard.schemas.masking import mask_dto

        masked = mask_dto(
            {
                "account": _raw_account_state(),
                "alerts": [{"details": {"balance": RAW_BALANCE}}],
            }
        )
        blob = json.dumps(masked)
        assert RAW_ACCOUNT_ID not in blob
        assert str(RAW_BALANCE) not in blob
        assert str(RAW_EQUITY) not in blob
        assert RAW_ACCOUNT_NAME not in blob


# ═══════════════════════════════════════════════════════════════════
# 2 — Streaming DTO is masked (WS broadcast + SSE share this builder)
# ═══════════════════════════════════════════════════════════════════


class TestLiveStateIsMasked:
    """The broadly shared stream must never carry raw account financials."""

    @pytest.fixture(autouse=True)
    def _fake_state_service(self, monkeypatch: pytest.MonkeyPatch):
        import eigencapital.dashboard.services.dashboard_state as dashboard_state

        monkeypatch.setattr(dashboard_state, "DashboardStateService", _FakeStateService)

    @staticmethod
    def _live_state() -> dict[str, Any]:
        from eigencapital.dashboard.streaming.events import get_live_state

        return asyncio.run(get_live_state())

    def test_raw_account_id_absent_from_stream(self) -> None:
        blob = json.dumps(self._live_state())
        assert RAW_ACCOUNT_ID not in blob

    def test_raw_balance_absent_from_stream(self) -> None:
        blob = json.dumps(self._live_state())
        assert str(RAW_BALANCE) not in blob
        assert str(RAW_EQUITY) not in blob

    def test_raw_position_notional_absent_from_stream(self) -> None:
        blob = json.dumps(self._live_state())
        assert str(RAW_ENTRY_PRICE) not in blob
        assert "123.45" not in blob  # risk observation value / alert details

    def test_masked_values_are_present_and_numeric(self) -> None:
        state = self._live_state()
        assert state["type"] == "state_update"
        account = state["data"]["account"]
        assert account["balance"] == pytest.approx(10400.0)
        assert isinstance(account["balance"], float)
        assert account["equity"] == pytest.approx(12300.0)
        positions = state["data"]["positions"]
        assert positions and positions[0]["entry_price"] == pytest.approx(2500.0)

    def test_account_id_masked_keeps_last_four(self) -> None:
        account = self._live_state()["data"]["account"]
        masked_id = account["account_id"]
        assert masked_id.endswith(RAW_ACCOUNT_ID[-4:])
        assert RAW_ACCOUNT_ID not in masked_id

    def test_names_truncated_in_stream(self) -> None:
        account = self._live_state()["data"]["account"]
        assert account["account_name"] != RAW_ACCOUNT_NAME
        assert len(account["account_name"]) <= 33

    def test_stream_structure_is_unchanged(self) -> None:
        data = self._live_state()["data"]
        assert set(data) == {"account", "positions", "health", "risk", "alerts"}
        assert data["health"]["overall_state"] == "HEALTHY"
        assert data["risk"]["overall_level"] == "NORMAL"
        assert isinstance(data["alerts"], list)


# ═══════════════════════════════════════════════════════════════════
# 3 — Authenticated API keeps exact values (H-11 key check intact)
# ═══════════════════════════════════════════════════════════════════


class TestAuthenticatedApiKeepsExactValues:
    """Masking is for the broad stream only — REST stays exact + key-guarded."""

    @pytest.fixture(autouse=True)
    def _env_and_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DASHBOARD_DISABLE_AUTH", raising=False)
        monkeypatch.setenv("DASHBOARD_API_KEY", API_KEY)

        from eigencapital.dashboard.api.app import app
        from eigencapital.dashboard.api.routes import portfolio

        app.dependency_overrides[portfolio.get_state_service] = _FakeStateService
        try:
            yield app
        finally:
            app.dependency_overrides.pop(portfolio.get_state_service, None)

    @staticmethod
    def _get(app: Any, path: str, headers: dict[str, str] | None = None) -> Any:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            return client.get(path, headers=headers or {})

    def test_account_endpoint_returns_exact_balance(self, _env_and_override) -> None:
        response = self._get(
            _env_and_override,
            "/api/v1/portfolio/account",
            headers={"X-API-Key": API_KEY},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["balance"] == RAW_BALANCE
        assert body["equity"] == RAW_EQUITY
        assert body["daily_pnl"] == 123.45

    def test_positions_endpoint_returns_exact_prices(self, _env_and_override) -> None:
        response = self._get(
            _env_and_override,
            "/api/v1/portfolio/positions",
            headers={"X-API-Key": API_KEY},
        )
        assert response.status_code == 200
        positions = response.json()
        assert positions[0]["entry_price"] == RAW_ENTRY_PRICE
        assert positions[0]["unrealized_pnl"] == 10.55

    def test_exact_values_still_require_the_api_key(self, _env_and_override) -> None:
        """The API-key check (H-11) must not be weakened by masking."""
        assert self._get(_env_and_override, "/api/v1/portfolio/account").status_code == 401
        assert (
            self._get(
                _env_and_override,
                "/api/v1/portfolio/account",
                headers={"X-API-Key": "wrong-key"},
            ).status_code
            == 401
        )

    def test_stream_is_masked_where_rest_is_exact(self, _env_and_override) -> None:
        """Same fake data: REST exact, stream masked — both in one scenario."""
        import eigencapital.dashboard.services.dashboard_state as dashboard_state
        from eigencapital.dashboard.streaming.events import get_live_state

        rest = self._get(
            _env_and_override,
            "/api/v1/portfolio/account",
            headers={"X-API-Key": API_KEY},
        )
        with patch.object(dashboard_state, "DashboardStateService", _FakeStateService):
            stream = asyncio.run(get_live_state())

        assert rest.json()["balance"] == RAW_BALANCE
        assert stream["data"]["account"]["balance"] != RAW_BALANCE
        assert str(RAW_BALANCE) not in json.dumps(stream)


# ═══════════════════════════════════════════════════════════════════
# 4 — Client (dashboard/src/**) static checks
# ═══════════════════════════════════════════════════════════════════


class TestClientSourceHasNoRawFinancials:
    """The frontend has no JS test runner (L-6); check its sources here."""

    @staticmethod
    def _sources() -> list[tuple[Path, str]]:
        src = Path("dashboard/src")
        if not src.is_dir():  # pragma: no cover - repo layout guard
            return []
        return [
            (path, path.read_text(encoding="utf-8"))
            for pattern in ("*.ts", "*.tsx")
            for path in sorted(src.rglob(pattern))
        ]

    def test_no_hardcoded_production_account_id(self) -> None:
        """The production account ID must never be baked into the bundle."""
        for path, text in self._sources():
            assert "436921728" not in text, path

    def test_no_hardcoded_balance_literals(self) -> None:
        """No raw balance/equity figures hardcoded into client components."""
        pattern = re.compile(r"\b(balance|equity)\s*[:=]\s*\d{4,}(\.\d+)?\b")
        for path, text in self._sources():
            match = pattern.search(text)
            assert match is None, f"{path}: {match.group(0) if match else ''}"

    def test_no_local_financial_persistence(self) -> None:
        """Raw financial state must not be persisted in browser storage."""
        for path, text in self._sources():
            assert "localStorage" not in text, path
            assert "sessionStorage" not in text, path

    def test_money_formatting_stays_centralized(self) -> None:
        """One formatter (lib/utils formatCurrency) — no ad-hoc currency math."""
        utils_path = Path("dashboard/src/lib/utils.ts")
        utils = utils_path.read_text(encoding="utf-8")
        assert "formatCurrency" in utils
        for path, text in self._sources():
            if path == utils_path:
                continue
            assert "Intl.NumberFormat" not in text, path
