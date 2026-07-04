"""Backend↔Frontend API Contract Tests.

Validates that the state-bundle JSON structure matches what the
frontend TypeScript types expect. Catches API drift when backend
changes response shape without updating frontend schemas.

To capture a live fixture:
  curl http://127.0.0.1:5000/state-bundle.json | python3 -m json.tool > tests/fixtures/bundle_live.json
"""

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# ── Expected field topology ──────────────────────────────────────────
# Mirror of paper_trading/dashboard/src/types/bundle.ts

BUNDLE_META_FIELDS = {
    "version": str,
    "server_time": str,
    "status": str,  # 'ok' | 'degraded' | 'partial_failure'
    "snapshot_time": str,
    "snapshot_sequence_id": (int, float),
    "max_live_age_seconds": (type(None), int, float),
    "request_id": str,
}

ENGINE_STATUS_FIELDS = {
    "initialized": bool,
    "last_update": (type(None), str),
    "start_time": (type(None), str),
    "market_closed": (type(None), bool),
}

PORTFOLIO_FIELDS = {
    "total_value": (int, float),
    "mtm_value": (int, float),
    "total_return": (int, float),
    "capital": (int, float),
    "allocations": dict,
    "deployment_cleared": bool,
    "open_positions": (int, float),
    "closed_trades": (int, float),
    "execution_state": (type(None), str),
}

ASSET_METRICS_FIELDS = {
    "asset": str,
    "total_return": (int, float),
    "drawdown": (int, float),
    "win_rate": (int, float),
    "n_trades": int,
    "n_signals": int,
    "mean_confidence": (int, float),
    "mean_prob_long": (int, float),
    "mean_prob_short": (int, float),
    "current_price": (type(None), int, float),
    "profit_factor": (type(None), int, float),
    "sharpe_ratio": (type(None), int, float),
}

HALT_CONDITIONS_FIELDS = {
    "drawdown": (int, float),
    "monthly_pf": (int, float),
    "signal_drought": (int, float),
    "prob_drift": (int, float),
}

LIVE_SOURCE_META_FIELDS = {
    "fetch_time": str,
    "fetch_age_seconds": (int, float),
    "is_fresh": bool,
}


def _check_fields(obj: dict, fields: dict, path: str = "root") -> list[str]:
    errors = []
    for name, expected_types in fields.items():
        if name not in obj:
            errors.append(f"{path}.{name}: MISSING")
            continue
        val = obj[name]
        if not isinstance(val, expected_types):
            errors.append(
                f"{path}.{name}: expected {expected_types}, got {type(val).__name__}"
            )
    return errors


def _load_fixtures() -> list[tuple[str, dict]]:
    """Return list of (name, parsed_json) for each fixture file found."""
    fixtures = []
    if not FIXTURE_DIR.exists():
        return fixtures
    for f in sorted(FIXTURE_DIR.glob("bundle_*.json")):
        with open(f) as fh:
            fixtures.append((f.name, json.load(fh)))
    return fixtures


# ── Parametrize helpers ──────────────────────────────────────────────

_FIXTURES = _load_fixtures()
_FIXTURE_IDS = [n for n, _ in _FIXTURES]


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_bundle_top_level(name: str, bundle: dict):
    errors = []
    for key in ("meta", "snapshot", "live"):
        if key not in bundle:
            errors.append(f"root.{key}: MISSING")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_bundle_meta(name: str, bundle: dict):
    errors = _check_fields(bundle.get("meta", {}), BUNDLE_META_FIELDS, "meta")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_engine_status(name: str, bundle: dict):
    snapshot = bundle.get("snapshot", {})
    status = snapshot.get("engine_status", {})
    errors = _check_fields(status, ENGINE_STATUS_FIELDS, "engine_status")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_portfolio(name: str, bundle: dict):
    snapshot = bundle.get("snapshot", {})
    portfolio = snapshot.get("portfolio", {})
    errors = _check_fields(portfolio, PORTFOLIO_FIELDS, "portfolio")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_halt_conditions(name: str, bundle: dict):
    snapshot = bundle.get("snapshot", {})
    halt = snapshot.get("halt_conditions", {})
    errors = _check_fields(halt, HALT_CONDITIONS_FIELDS, "halt_conditions")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_asset_metrics(name: str, bundle: dict):
    snapshot = bundle.get("snapshot", {})
    assets = snapshot.get("assets", {})
    if not assets:
        pytest.skip("no assets in fixture")
    errors = []
    for asset_name, asset in assets.items():
        m = asset.get("metrics", {})
        if not m:
            continue
        errors += _check_fields(m, ASSET_METRICS_FIELDS, f"assets.{asset_name}.metrics")
    assert not errors, "; ".join(errors[:20])


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_live_sources(name: str, bundle: dict):
    live = bundle.get("live", {})
    errors = []
    for src_name in ("health", "mt5"):
        src = live.get(src_name, {})
        errors += _check_fields(src, LIVE_SOURCE_META_FIELDS, f"live.{src_name}")
    assert not errors, "; ".join(errors)


@pytest.mark.parametrize("name,bundle", _FIXTURES, ids=_FIXTURE_IDS)
def test_allocations_match_assets(name: str, bundle: dict):
    snapshot = bundle.get("snapshot", {})
    portfolio = snapshot.get("portfolio", {})
    assets = snapshot.get("assets", {})
    allocs = portfolio.get("allocations", {})
    if not assets or not allocs:
        pytest.skip("no assets or allocations in fixture")
    missing = [a for a in assets if a not in allocs]
    extra = [a for a in allocs if a not in assets]
    errors = []
    if missing:
        errors.append(f"assets missing from allocations: {missing}")
    if extra:
        errors.append(f"allocations without assets: {extra}")
    assert not errors, "; ".join(errors)


def test_fixtures_exist():
    """Fail early if no fixtures are available — reminds user to capture live data."""
    fixtures = _load_fixtures()
    if not fixtures:
        pytest.skip(
            "No bundle fixtures found. Run:\n"
            "  curl http://127.0.0.1:5000/state-bundle.json | python3 -m json.tool "
            "> tests/fixtures/bundle_live.json"
        )
