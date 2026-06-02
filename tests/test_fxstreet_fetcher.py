import json
import os
import pytest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta

from features.macro_narrative import MacroNarrativeFeatures
from features.fxstreet_fetcher import (
    fetch_fxstreet_article,
    call_llm,
    run_weekly_narrative_pipeline,
    confirm_pending_narrative,
    get_active_narrative,
    get_pending_narrative,
    is_narrative_stale,
    get_fetch_error,
    get_narrative_status,
    _write_error,
    NARRATIVE_PENDING,
    NARRATIVE_ACTIVE,
    NARRATIVE_DIR,
    NARRATIVE_ERROR,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_html():
    return '<html><a href="/analysis/week-ahead-fx-2026">Week Ahead</a><div class="article-content"><p>USD strengthens on hawkish Fed outlook.</p></div></html>'


@pytest.fixture
def sample_weekly_outlook_html():
    return '<html><a href="/analysis/weekly-outlook">Weekly Outlook</a><div class="article-content"><p>Markets calm this week.</p></div></html>'


@pytest.fixture
def sample_llm_json():
    return {
        "usd_strength_narrative": 0.7,
        "geopol_risk_score": 0.4,
        "fed_hawkishness": 0.8,
        "rbnz_hawkishness": 0.3,
        "rba_hawkishness": 0.4,
        "boj_intervention_risk": 0.2,
        "energy_crisis_pressure": 0.3,
        "usd_bias": "bullish",
        "nzd_bias": "neutral",
        "aud_bias": "neutral",
        "jpy_bias": "bearish",
        "cad_bias": "neutral",
        "eur_bias": "bearish",
        "key_events": ["FOMC decision", "NFP Friday"],
        "overall_regime": "data_driven",
        "confidence": 0.75,
    }


@pytest.fixture
def sample_narrative(tmp_path):
    return MacroNarrativeFeatures(
        week_start="2026-05-25",
        usd_strength_narrative=0.5,
        geopol_risk_score=0.3,
        fed_hawkishness=0.5,
        rbnz_hawkishness=0.5,
        rba_hawkishness=0.5,
        boj_intervention_risk=0.3,
        energy_crisis_pressure=0.3,
        usd_bias="neutral",
        nzd_bias="neutral",
        aud_bias="neutral",
        jpy_bias="neutral",
        cad_bias="neutral",
        eur_bias="neutral",
        key_events=[],
        overall_regime="data_driven",
        confidence=0.5,
    )


# ── fetch_fxstreet_article ───────────────────────────────────────────────────

def _make_fxstreet_mock_resp(text, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@patch("features.fxstreet_fetcher.requests.get")
def test_fetch_fxstreet_returns_text(mock_get):
    listing_page = '<html><a href="/weekly-forex-forecast">Weekly forex forecast</a></html>'
    article_page = (
        '<html><div class="overflow-clip">'
        'Weekly forex forecast: EUR/USD, Gold, Bitcoin and more'
        'USD strengthens on hawkish Fed outlook. The Federal Reserve maintained its hawkish stance during the latest FOMC meeting, signaling that rates will remain elevated for longer. This has provided strong support for the US dollar across the board. Market participants are now pricing in a higher probability of additional rate hikes if inflation does not moderate as expected.'
        'EURUSD tested key support levels as the euro struggled amid a widening interest rate differential. The ECB\'s more cautious approach contrasts sharply with the Fed\'s determination to keep policy restrictive, which continues to weigh on the single currency. Analysts expect further downside risks for EURUSD in the near term.'
        'Commodity currencies were mixed, with the Australian dollar showing resilience on the back of stronger-than-expected employment data. The RBA\'s recent rate hike has provided some support, though global growth concerns remain a headwind for risk-sensitive currencies.'
        '</div></html>'
    )
    mock_get.side_effect = [
        _make_fxstreet_mock_resp(listing_page),
        _make_fxstreet_mock_resp(article_page),
    ]
    result = fetch_fxstreet_article()
    assert isinstance(result, str)
    assert "USD strengthens" in result


@patch("features.fxstreet_fetcher.requests.get")
def test_fetch_fxstreet_no_article_found(mock_get):
    mock_get.return_value = _make_fxstreet_mock_resp(
        "<html><body>No relevant articles here</body></html>"
    )
    result = fetch_fxstreet_article()
    assert result is None


@patch("features.fxstreet_fetcher.requests.get")
def test_fetch_fxstreet_handles_network_error(mock_get):
    mock_get.side_effect = ConnectionError("timeout")
    result = fetch_fxstreet_article()
    assert result is None


@patch("features.fxstreet_fetcher.requests.get")
def test_fetch_fxstreet_handles_http_error(mock_get):
    mock_get.return_value = _make_fxstreet_mock_resp("", status_code=503)
    mock_get.return_value.raise_for_status.side_effect = Exception("HTTP 503")
    result = fetch_fxstreet_article()
    assert result is None


@patch("features.fxstreet_fetcher.requests.get")
def test_fetch_fxstreet_weekly_outlook_fallback(mock_get):
    listing_page = '<html><div class="text-body-md">Markets calm this week as traders await key economic data releases. The US dollar traded in a tight range against major peers as investors digested the latest Fed commentary.</div></html>'
    article_page = None  # not reached; Strategy 2 should catch it
    mock_get.side_effect = [
        _make_fxstreet_mock_resp(listing_page),
        _make_fxstreet_mock_resp(article_page),
    ]
    result = fetch_fxstreet_article()
    assert isinstance(result, str)
    assert "Markets calm" in result


# ── call_llm ─────────────────────────────────────────────────────────────────

@patch("features.fxstreet_fetcher.requests.post")
def test_call_llm_returns_parsed_json(mock_post, sample_llm_json):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(sample_llm_json)}}]
    }
    mock_post.return_value = mock_resp

    result = call_llm("Some text", "fake-api-key")
    assert result is not None
    assert result["usd_strength_narrative"] == 0.7


@patch("features.fxstreet_fetcher.requests.post")
def test_call_llm_handles_no_choices(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {}
    mock_post.return_value = mock_resp

    result = call_llm("Some text", "fake-api-key")
    assert result is None


@patch("features.fxstreet_fetcher.requests.post")
def test_call_llm_handles_no_json_in_response(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Just text without JSON"}}]
    }
    mock_post.return_value = mock_resp

    result = call_llm("Some text", "fake-api-key")
    assert result is None


@patch("features.fxstreet_fetcher.requests.post")
def test_call_llm_handles_network_error(mock_post):
    mock_post.side_effect = ConnectionError("API unreachable")
    result = call_llm("Some text", "fake-api-key")
    assert result is None


@patch("features.fxstreet_fetcher.requests.post")
def test_call_llm_handles_invalid_json(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "{invalid json}"}}]
    }
    mock_post.return_value = mock_resp

    result = call_llm("Some text", "fake-api-key")
    assert result is None


# ── run_weekly_narrative_pipeline ────────────────────────────────────────────

@patch("features.fxstreet_fetcher.fetch_fxstreet_article")
@patch("features.fxstreet_fetcher.save_narrative_json")
def test_pipeline_no_article_returns_false(mock_save, mock_fetch, tmp_path):
    mock_fetch.return_value = None
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "narrative_error.json")):
        result = run_weekly_narrative_pipeline()
        assert result is False


@patch("features.fxstreet_fetcher.fetch_fxstreet_article")
@patch("features.fxstreet_fetcher.call_llm")
@patch("features.fxstreet_fetcher.save_narrative_json")
def test_pipeline_with_api_key(mock_save, mock_llm, mock_fetch, sample_llm_json, tmp_path):
    mock_fetch.return_value = "Some article text"
    mock_llm.return_value = sample_llm_json
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "narrative_pending.json")):
        result = run_weekly_narrative_pipeline(api_key="fake-key")
        assert result is True
        mock_save.assert_called_once()


@patch("features.fxstreet_fetcher.fetch_fxstreet_article")
@patch("features.fxstreet_fetcher.call_llm")
def test_pipeline_llm_failure(mock_llm, mock_fetch, tmp_path):
    mock_fetch.return_value = "Some article text"
    mock_llm.return_value = None
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "narrative_error.json")):
        result = run_weekly_narrative_pipeline(api_key="fake-key")
        # Falls back to neutral narrative (does not propagate the failure)
        assert result is True
        assert os.path.exists(tmp_path / "narrative_error.json")


@patch("features.fxstreet_fetcher.fetch_fxstreet_article")
@patch("features.fxstreet_fetcher.neutral_narrative")
@patch("features.fxstreet_fetcher.save_narrative_json")
def test_pipeline_no_api_key_uses_neutral(mock_save, mock_neutral, mock_fetch, sample_narrative, tmp_path):
    mock_fetch.return_value = "Some article text"
    mock_neutral.return_value = sample_narrative
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "narrative_pending.json")):
        result = run_weekly_narrative_pipeline()
        assert result is True
        mock_save.assert_called_once()


# ── confirm_pending_narrative ────────────────────────────────────────────────

def test_confirm_pending_no_file(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "nonexistent.json")), \
         patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(tmp_path / "active.json")):
        result = confirm_pending_narrative()
        assert result is False


def test_confirm_pending_success(tmp_path):
    pending = tmp_path / "narrative_pending.json"
    active = tmp_path / "narrative_active.json"
    error_file = tmp_path / "narrative_error.json"
    pending.write_text('{"week_start": "2026-05-25", "confidence": 0.5}')
    error_file.write_text('{"reason": "old_error"}')

    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(pending)), \
         patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(active)), \
         patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(error_file)):
        result = confirm_pending_narrative()
        assert result is True
        assert active.exists()
        assert not error_file.exists()


def test_confirm_pending_copy_failure(tmp_path):
    pending = tmp_path / "narrative_pending.json"
    active = tmp_path / "narrative_active.json"
    pending.write_text('{}')
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(pending)), \
         patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(active)):
        import shutil
        original = shutil.copy2
        shutil.copy2 = MagicMock(side_effect=PermissionError("denied"))
        try:
            result = confirm_pending_narrative()
            assert result is False
        finally:
            shutil.copy2 = original


# ── get_active_narrative / get_pending_narrative ─────────────────────────────

def test_get_active_narrative_no_file(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(tmp_path / "nonexistent.json")):
        result = get_active_narrative()
        assert result is None


def test_get_active_narrative_success(tmp_path, sample_narrative):
    path = tmp_path / "narrative_active.json"
    path.write_text(json.dumps(sample_narrative.to_dict()))
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(path)):
        result = get_active_narrative()
        assert result is not None
        assert result.week_start == "2026-05-25"


def test_get_active_narrative_corrupt_file(tmp_path):
    path = tmp_path / "narrative_active.json"
    path.write_text("{invalid")
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(path)):
        result = get_active_narrative()
        assert result is None


def test_get_pending_narrative_no_file(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "nonexistent.json")):
        result = get_pending_narrative()
        assert result is None


def test_get_pending_narrative_success(tmp_path, sample_narrative):
    path = tmp_path / "narrative_pending.json"
    path.write_text(json.dumps(sample_narrative.to_dict()))
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(path)):
        result = get_pending_narrative()
        assert result is not None
        assert result.week_start == "2026-05-25"


def test_get_pending_narrative_corrupt_file(tmp_path):
    path = tmp_path / "narrative_pending.json"
    path.write_text("{bad")
    with patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(path)):
        result = get_pending_narrative()
        assert result is None


# ── is_narrative_stale ───────────────────────────────────────────────────────

def test_narrative_not_stale():
    week_start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    assert is_narrative_stale(week_start) is False


def test_narrative_stale_exactly_7_days():
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    assert is_narrative_stale(week_start) is True


def test_narrative_stale_old():
    week_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    assert is_narrative_stale(week_start) is True


def test_narrative_stale_invalid_date():
    assert is_narrative_stale("not-a-date") is True


def test_narrative_stale_empty_string():
    assert is_narrative_stale("") is True


# ── _write_error ─────────────────────────────────────────────────────────────

def test_write_error_creates_file(tmp_path):
    error_path = tmp_path / "narrative_error.json"
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(error_path)):
        _write_error("test_reason", "test_detail")
        assert error_path.exists()
        data = json.loads(error_path.read_text())
        assert data["reason"] == "test_reason"
        assert data["detail"] == "test_detail"


def test_write_error_handles_exception(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", "/nonexistent/dir/error.json"):
        _write_error("reason", "detail")  # should not raise


# ── get_fetch_error ──────────────────────────────────────────────────────────

def test_get_fetch_error_no_file(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "nonexistent.json")):
        result = get_fetch_error()
        assert result is None


def test_get_fetch_error_success(tmp_path):
    path = tmp_path / "narrative_error.json"
    data = {"reason": "scrape_failed", "detail": "connection error"}
    path.write_text(json.dumps(data))
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(path)):
        result = get_fetch_error()
        assert result == data


def test_get_fetch_error_corrupt(tmp_path):
    path = tmp_path / "narrative_error.json"
    path.write_text("{bad")
    with patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(path)):
        result = get_fetch_error()
        assert result is None


# ── get_narrative_status ─────────────────────────────────────────────────────

def test_narrative_status_no_files(tmp_path):
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(tmp_path / "nonexistent_active.json")), \
         patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "nonexistent_pending.json")), \
         patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "nonexistent_error.json")):
        status = get_narrative_status()
        assert status["active"] is None
        assert status["pending"] is None
        assert status["stale"] is True
        assert status["fetch_error"] is None
        assert status["has_pending"] is False
        assert status["needs_confirmation"] is False


def test_narrative_status_with_active(tmp_path, sample_narrative):
    active_path = tmp_path / "narrative_active.json"
    active_path.write_text(json.dumps(sample_narrative.to_dict()))
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(active_path)), \
         patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(tmp_path / "nonexistent.json")), \
         patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "nonexistent.json")):
        status = get_narrative_status()
        assert status["active"] is not None
        assert status["active"]["week_start"] == "2026-05-25"


def test_narrative_status_needs_confirmation(tmp_path, sample_narrative):
    active_path = tmp_path / "narrative_active.json"
    pending_path = tmp_path / "narrative_pending.json"
    active_path.write_text(json.dumps(sample_narrative.to_dict()))
    pending_features = sample_narrative.to_dict()
    pending_features["week_start"] = "2026-06-01"
    pending_path.write_text(json.dumps(pending_features))
    with patch("features.fxstreet_fetcher.NARRATIVE_ACTIVE", str(active_path)), \
         patch("features.fxstreet_fetcher.NARRATIVE_PENDING", str(pending_path)), \
         patch("features.fxstreet_fetcher.NARRATIVE_ERROR", str(tmp_path / "nonexistent.json")):
        status = get_narrative_status()
        assert status["has_pending"] is True
        assert status["needs_confirmation"] is True
