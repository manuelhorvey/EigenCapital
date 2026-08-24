"""Unit tests for Instrument Catalogue."""

import pytest
from eigencapital.core.models.instrument import Instrument
from eigencapital.data.catalogue.catalogue import (
    InstrumentCatalogue,
    InstrumentNotFoundError,
    DuplicateInstrumentError,
)
from eigencapital.data.catalogue.schemas import (
    CATALOGUE,
    build_initial_catalogue,
)


@pytest.fixture(autouse=True)
def clear_instruments():
    """Clear instrument registries between tests."""
    Instrument._registry.clear()
    yield
    Instrument._registry.clear()


_counter = 0


def _make_instrument(**overrides):
    global _counter
    _counter += 1
    defaults = dict(
        instrument_id=f"TEST_{_counter}",
        symbol="Test",
        asset_class="EQUITY",
        venue="TEST",
        quote_currency="USD",
        tick_size=0.01,
        tick_value=1.0,
        lot_size=1,
        price_precision=2,
    )
    defaults.update(overrides)
    return Instrument(**defaults)


class TestCatalogue:
    def test_register_and_get(self):
        cat = InstrumentCatalogue()
        inst = _make_instrument(instrument_id="T1")
        cat.register(inst)
        assert cat.get("T1") == inst

    def test_get_not_found(self):
        cat = InstrumentCatalogue()
        with pytest.raises(InstrumentNotFoundError):
            cat.get("NONEXISTENT")

    def test_duplicate_registration(self):
        cat = InstrumentCatalogue()
        inst = _make_instrument(instrument_id="T1")
        cat.register(inst)
        with pytest.raises(DuplicateInstrumentError):
            cat.register(inst)

    def test_contains(self):
        cat = InstrumentCatalogue()
        inst = _make_instrument(instrument_id="T1")
        cat.register(inst)
        assert cat.contains("T1")
        assert not cat.contains("T2")

    def test_len(self):
        cat = InstrumentCatalogue()
        assert len(cat) == 0
        cat.register(_make_instrument(instrument_id="T1"))
        assert len(cat) == 1

    def test_list_ids(self):
        cat = InstrumentCatalogue()
        cat.register(_make_instrument(instrument_id="C"))
        cat.register(_make_instrument(instrument_id="A"))
        cat.register(_make_instrument(instrument_id="B"))
        assert cat.list_ids() == ["A", "B", "C"]

    def test_iter(self):
        cat = InstrumentCatalogue()
        cat.register(_make_instrument(instrument_id="B"))
        cat.register(_make_instrument(instrument_id="A"))
        ids = [i.instrument_id for i in cat]
        assert ids == ["A", "B"]

    def test_contains_operator(self):
        cat = InstrumentCatalogue()
        cat.register(_make_instrument(instrument_id="T1"))
        assert "T1" in cat
        assert "T2" not in cat


class TestSchemas:
    def test_initial_catalogue_has_all(self):
        assert len(CATALOGUE) == 10

    def test_es_metadata(self):
        es = CATALOGUE.get("ES")
        assert es.tick_size == 0.25
        assert es.tick_value == 12.50
        assert es.asset_class == "EQUITY_FUTURE"
        assert es.venue == "CME"

    def test_fx_metadata(self):
        eurusd = CATALOGUE.get("EURUSD")
        assert eurusd.tick_size == 0.0001
        assert eurusd.asset_class == "FX"

    def test_crypto_metadata(self):
        btc = CATALOGUE.get("BTCUSD")
        assert btc.trading_calendar == "24x7x365"
        assert btc.asset_class == "CRYPTO"

    def test_equity_metadata(self):
        spy = CATALOGUE.get("SPY")
        assert spy.asset_class == "EQUITY"
        assert spy.venue == "NYSE"

    def test_build_initial_catalogue(self):
        cat = build_initial_catalogue()
        assert len(cat) == 10
        assert cat.contains("ES")
        assert cat.contains("BTCUSD")


class TestRepository:
    def test_save_and_load(self, tmp_path):
        from eigencapital.data.catalogue.repository import CatalogueRepository
        from eigencapital.core.models.instrument import Instrument

        repo = CatalogueRepository(tmp_path)
        inst = _make_instrument()
        repo.save(inst)
        Instrument._registry.clear()  # allow re-registration from disk
        loaded = repo.load(inst.instrument_id)
        assert loaded.instrument_id == inst.instrument_id

    def test_load_not_found(self, tmp_path):
        from eigencapital.data.catalogue.repository import CatalogueRepository
        from eigencapital.data.catalogue.catalogue import InstrumentNotFoundError

        repo = CatalogueRepository(tmp_path)
        with pytest.raises(InstrumentNotFoundError):
            repo.load("NONEXISTENT")

    def test_list_ids(self, tmp_path):
        from eigencapital.data.catalogue.repository import CatalogueRepository

        repo = CatalogueRepository(tmp_path)
        i1 = _make_instrument()
        i2 = _make_instrument()
        repo.save(i1)
        repo.save(i2)
        ids = repo.list_ids()
        assert i1.instrument_id in ids
        assert i2.instrument_id in ids

    def test_save_catalogue(self, tmp_path):
        from eigencapital.data.catalogue.repository import CatalogueRepository
        from eigencapital.core.models.instrument import Instrument

        repo = CatalogueRepository(tmp_path)
        cat = InstrumentCatalogue()
        i1 = _make_instrument()
        i2 = _make_instrument()
        cat.register(i1)
        cat.register(i2)
        repo.save_catalogue(cat)
        Instrument._registry.clear()  # allow re-registration from disk
        loaded = repo.load_all()
        assert len(loaded) == 2

    def test_delete(self, tmp_path):
        from eigencapital.data.catalogue.repository import CatalogueRepository

        repo = CatalogueRepository(tmp_path)
        inst = _make_instrument()
        repo.save(inst)
        assert repo.delete(inst.instrument_id) is True
        assert repo.exists(inst.instrument_id) is False
        assert repo.delete(inst.instrument_id) is False
