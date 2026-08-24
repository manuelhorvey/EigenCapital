"""Unit tests for EigenCapital domain models — MarketSnapshot.

Tests data quality, price validation, optional fields, serialization.
"""

from eigencapital.core.models.market_snapshot import MarketSnapshot, DataQualityStatus


_counter = 0


def _make_snapshot(**overrides):
    """Helper to create a MarketSnapshot with sensible defaults."""
    global _counter
    _counter += 1
    defaults = dict(
        instrument_id="ES",
        timestamp_utc=f"2024-03-15T09:35:{_counter:02d}Z",
        mid_price=4500.0,
        bid_price=4499.5,
        ask_price=4500.5,
        volume=1500,
        session="OPEN",
        data_quality=DataQualityStatus.VALID,
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def test_snapshot_creation():
    """Test basic MarketSnapshot creation."""
    ms = _make_snapshot()
    assert ms.instrument_id == "ES"
    assert ms.mid_price == 4500.0
    assert ms.bid_price == 4499.5
    assert ms.ask_price == 4500.5
    assert ms.volume == 1500
    assert ms.session == "OPEN"
    assert ms.data_quality == DataQualityStatus.VALID


def test_snapshot_optional_fields():
    """Test that optional fields can be None."""
    ms = _make_snapshot(mid_price=None, bid_price=None, ask_price=None)
    assert ms.mid_price is None
    assert ms.bid_price is None
    assert ms.ask_price is None


def test_snapshot_data_quality():
    """Test data quality validation."""
    for quality in (
        DataQualityStatus.VALID,
        DataQualityStatus.WARNING,
        DataQualityStatus.INVALID,
        DataQualityStatus.STALE,
    ):
        ms = _make_snapshot(data_quality=quality)
        assert ms.data_quality == quality

    try:
        _make_snapshot(data_quality="UNKNOWN")
        assert False, "Should reject unknown data quality"
    except ValueError:
        pass


def test_snapshot_session_validation():
    """Test session validation."""
    for session in ("OPEN", "CLOSED", "AUCTION"):
        ms = _make_snapshot(session=session)
        assert ms.session == session

    try:
        _make_snapshot(session="PRE_MARKET")
        assert False, "Should reject invalid session"
    except ValueError:
        pass


def test_snapshot_timestamp_format():
    """Test ISO-8601 timestamp validation."""
    ms = _make_snapshot(timestamp_utc="2024-03-15T09:35:00Z")
    assert "T" in ms.timestamp_utc

    try:
        _make_snapshot(timestamp_utc="2024-03-15 09:35:00")
        assert False, "Should reject non-ISO timestamp"
    except ValueError:
        pass


def test_snapshot_price_finiteness():
    """INVARIANT: Prices must be finite."""
    # NaN
    try:
        _make_snapshot(mid_price=float("nan"))
        assert False, "Should reject NaN mid_price"
    except ValueError:
        pass

    # Inf
    try:
        _make_snapshot(mid_price=float("inf"))
        assert False, "Should reject inf mid_price"
    except ValueError:
        pass


def test_snapshot_sizes_nonnegative():
    """INVARIANT: bid_size and ask_size >= 0."""
    ms = _make_snapshot(bid_size=100, ask_size=200)
    assert ms.bid_size == 100
    assert ms.ask_size == 200

    try:
        _make_snapshot(bid_size=-1)
        assert False, "Should reject negative bid_size"
    except ValueError:
        pass


def test_snapshot_mid_from_bid_ask():
    """Test mid_from_bid_ask property."""
    ms = _make_snapshot(bid_price=4499.0, ask_price=4501.0)
    assert ms.mid_from_bid_ask == 4500.0

    ms = _make_snapshot(bid_price=None, ask_price=4501.0)
    assert ms.mid_from_bid_ask is None


def test_snapshot_spread():
    """Test spread property."""
    ms = _make_snapshot(bid_price=4499.0, ask_price=4501.0)
    assert ms.spread == 2.0

    ms = _make_snapshot(bid_price=None)
    assert ms.spread is None


def test_snapshot_is_valid():
    """Test is_valid property."""
    ms = _make_snapshot(
        data_quality=DataQualityStatus.VALID,
        bid_price=4499.0,
        ask_price=4501.0,
    )
    assert ms.is_valid

    ms = _make_snapshot(data_quality=DataQualityStatus.STALE)
    assert not ms.is_valid


def test_snapshot_is_stale():
    """Test is_stale property."""
    ms = _make_snapshot(data_quality=DataQualityStatus.STALE)
    assert ms.is_stale

    ms = _make_snapshot(data_quality=DataQualityStatus.VALID)
    assert not ms.is_stale


def test_snapshot_to_from_dict():
    """Test deterministic serialization round-trip."""
    original = _make_snapshot()
    d = original.to_dict()

    MarketSnapshot._registry.clear()
    roundtrip = MarketSnapshot.from_dict(d)
    assert roundtrip.instrument_id == original.instrument_id
    assert roundtrip.mid_price == original.mid_price
    assert roundtrip.bid_price == original.bid_price
    assert roundtrip.ask_price == original.ask_price
    assert roundtrip.volume == original.volume


def test_snapshot_dict_consistency():
    """Test that to_dict produces consistent output."""
    ms = _make_snapshot()
    d1 = ms.to_dict()
    d2 = ms.to_dict()
    assert d1 == d2
