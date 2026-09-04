"""Unit tests for EigenCapital domain models — Instrument.

Tests invariants, validation, serialization, and deterministic behavior.
"""

from eigencapital.core.models.instrument import Instrument, validate_asset_class


def clear_registry():
    """Clear the class-level registry."""
    if hasattr(Instrument, "_registry"):
        Instrument._registry.clear()


def test_instrument_creation():
    """Test basic Instrument creation and invariants."""
    clear_registry()
    inst = Instrument(
        instrument_id="ES",
        symbol="S&P 500 E-mini",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
    )
    assert inst.instrument_id == "ES"
    assert inst.symbol == "S&P 500 E-mini"
    assert inst.tick_size == 0.25
    assert inst.tick_value == 50.0
    assert inst.lot_size == 1
    assert inst.price_precision == 2
    assert inst.quote_currency == "USD"
    assert inst.venue == "CME"
    assert inst.metadata_version == "v1"
    print("  PASS: test_instrument_creation")


def test_instrument_duplicate_id():
    """Duplicate instrument_ids are allowed at the model level.

    Instrument no longer keeps a process-global registry (B1 fix) — duplicate
    detection lives upstream (e.g., InstrumentCatalogue raises
    DuplicateInstrumentError on re-registration).
    """
    clear_registry()
    Instrument(
        instrument_id="ES1",
        symbol="S&P 500 E-mini",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
    )
    second = Instrument(
        instrument_id="ES1",  # same id — no class-level registry to collide with
        symbol="Different",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
    )
    assert second.instrument_id == "ES1"
    print("  PASS: test_instrument_duplicate_id")


def test_instrument_invalid_tick_size():
    """Test that invalid tick_size raises error."""
    clear_registry()
    try:
        Instrument(
            instrument_id="BAD",
            symbol="Bad",
            asset_class="EQUITY_FUTURE",
            venue="CME",
            quote_currency="USD",
            tick_size=0,  # invalid: must be > 0
            tick_value=50.0,
            lot_size=1,
            price_precision=2,
        )
        raise AssertionError("Should have raised ValueError for invalid tick_size")
    except ValueError as e:
        assert "tick_size must be > 0" in str(e)
    print("  PASS: test_instrument_invalid_tick_size")


def test_instrument_invalid_lot_size():
    """Test that invalid lot_size raises error."""
    clear_registry()
    try:
        Instrument(
            instrument_id="BAD",
            symbol="Bad",
            asset_class="EQUITY_FUTURE",
            venue="CME",
            quote_currency="USD",
            tick_size=0.25,
            tick_value=50.0,
            lot_size=0,  # invalid
            price_precision=2,
        )
        raise AssertionError("Should have raised ValueError for invalid lot_size")
    except ValueError as e:
        assert "lot_size must be > 0" in str(e)
    print("  PASS: test_instrument_invalid_lot_size")


def test_instrument_invalid_price_precision():
    """Test that invalid price_precision raises error."""
    clear_registry()
    try:
        Instrument(
            instrument_id="BAD",
            symbol="Bad",
            asset_class="EQUITY_FUTURE",
            venue="CME",
            quote_currency="USD",
            tick_size=0.25,
            tick_value=50.0,
            lot_size=1,
            price_precision=-1,  # invalid: must be >= 0
        )
        raise AssertionError("Should have raised ValueError for invalid price_precision")
    except ValueError as e:
        assert "price_precision must be >= 0" in str(e)
    print("  PASS: test_instrument_invalid_price_precision")


def test_instrument_invalid_asset_class():
    """Test that invalid asset_class raises error via validate_asset_class."""
    try:
        validate_asset_class("INVALID_CLASS")
        raise AssertionError("Should have raised ValueError for invalid asset class")
    except ValueError as e:
        assert "Invalid asset_class" in str(e)
    print("  PASS: test_instrument_invalid_asset_class")


def test_instrument_to_from_dict():
    """Test deterministic serialization round-trip."""
    clear_registry()
    original = Instrument(
        instrument_id="NQ",
        symbol="Nasdaq E-mini",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=20.0,
        lot_size=1,
        price_precision=2,
    )
    d = original.to_dict()
    # Verify dict has all expected keys
    assert "instrument_id" in d
    assert "symbol" in d
    assert "tick_size" in d
    # Round-trip: from_dict -> new instance
    roundtrip = Instrument.from_dict(d)
    assert roundtrip.instrument_id == original.instrument_id
    assert roundtrip.symbol == original.symbol
    assert roundtrip.tick_size == original.tick_size
    assert roundtrip.tick_value == original.tick_value
    assert roundtrip.price_precision == original.price_precision
    print("  PASS: test_instrument_to_from_dict")


def test_instrument_dict_sorted():
    """Test that to_dict produces consistent output (key ordering)."""
    clear_registry()
    original = Instrument(
        instrument_id="ES",
        symbol="S&P 500",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
    )

    d1 = original.to_dict()
    d2 = original.to_dict()

    # Two calls should produce identical dicts (deterministic)
    assert d1 == d2

    # Keys should be in insertion order (Python 3.7+ preserves dict order)
    # but the important thing is consistency
    assert list(d1.keys()) == list(d2.keys())
    print("  PASS: test_instrument_dict_sorted")


def test_instrument_config_hash():
    """Test that config_hash is deterministic."""
    clear_registry()
    original = Instrument(
        instrument_id="ES",
        symbol="S&P 500",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
    )

    h1 = original.config_hash()
    h2 = original.config_hash()

    # Same instrument should always produce same hash
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex length
    assert len(h2) == 64
    print("  PASS: test_instrument_config_hash")


def test_instrument_negative_tick_value():
    """Test that negative tick_value raises error."""
    clear_registry()
    try:
        Instrument(
            instrument_id="BAD",
            symbol="Bad",
            asset_class="EQUITY_FUTURE",
            venue="CME",
            quote_currency="USD",
            tick_size=0.25,
            tick_value=-50.0,  # invalid
            lot_size=1,
            price_precision=2,
        )
        raise AssertionError("Should have raised ValueError for negative tick_value")
    except ValueError as e:
        assert "tick_value must be > 0" in str(e)
    print("  PASS: test_instrument_negative_tick_value")


def test_instrument_currency_conversion():
    """Test currency_conversion_rate defaults to 1.0."""
    clear_registry()
    inst = Instrument(
        instrument_id="EUR_USD",
        symbol="EUR/USD",
        asset_class="FX",
        venue="FXCM",
        quote_currency="USD",
        tick_size=0.0001,
        tick_value=10000.0,
        lot_size=100000,
        price_precision=4,
    )
    assert inst.currency_conversion_rate == 1.0
    print("  PASS: test_instrument_currency_conversion")


def test_instrument_with_timezone():
    """Test Instrument with timezone set."""
    clear_registry()
    inst = Instrument(
        instrument_id="ES",
        symbol="S&P 500",
        asset_class="EQUITY_FUTURE",
        venue="CME",
        quote_currency="USD",
        tick_size=0.25,
        tick_value=50.0,
        lot_size=1,
        price_precision=2,
        timezone="America/Chicago",
    )
    assert inst.timezone == "America/Chicago"
    print("  PASS: test_instrument_with_timezone")


def test_instrument_validate_asset_class():
    """Test the validate_asset_class helper."""
    # Valid classes
    for valid in ["EQUITY_FUTURE", "FX", "EQUITY", "CRYPTO", "RATES"]:
        try:
            validate_asset_class(valid)
        except ValueError:
            raise AssertionError(f"validate_asset_class({valid}) should not raise")

    # Invalid classes
    for invalid in ["EQUITY_OPTION", "FUTURE_OPTION", "BOND", "INVALID"]:
        try:
            validate_asset_class(invalid)
            raise AssertionError(f"validate_asset_class({invalid}) should raise ValueError")
        except ValueError:
            pass  # Expected

    print("  PASS: test_instrument_validate_asset_class")


if __name__ == ".__main__":
    # Run all tests
    test_instrument_creation()
    test_instrument_duplicate_id()
    test_instrument_invalid_tick_size()
    test_instrument_invalid_lot_size()
    test_instrument_invalid_price_precision()
    test_instrument_invalid_asset_class()
    test_instrument_to_from_dict()
    test_instrument_dict_sorted()
    test_instrument_config_hash()
    test_instrument_negative_tick_value()
    test_instrument_currency_conversion()
    test_instrument_with_timezone()
    test_instrument_validate_asset_class()
    print("\nAll Instrument tests passed!")
