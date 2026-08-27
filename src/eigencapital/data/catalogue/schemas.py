"""Initial instrument catalogue entries.

These are representative cross-asset fixtures for development and testing.
They are NOT a claim that all these instruments will eventually be traded.

Usage:
    from eigencapital.data.catalogue.schemas import CATALOGUE
    es = CATALOGUE.get("ES")
"""

from eigencapital.core.models.instrument import Instrument
from eigencapital.data.catalogue.catalogue import InstrumentCatalogue

# ─── Futures ────────────────────────────────────────────────────────────────

ES = Instrument(
    instrument_id="ES",
    symbol="S&P 500 E-mini",
    asset_class="EQUITY_FUTURE",
    venue="CME",
    quote_currency="USD",
    tick_size=0.25,
    tick_value=12.50,
    lot_size=1,
    price_precision=2,
    timezone="America/Chicago",
    expiration_rule="quarterly (Mar, Jun, Sep, Dec)",
)

NQ = Instrument(
    instrument_id="NQ",
    symbol="Nasdaq 100 E-mini",
    asset_class="EQUITY_FUTURE",
    venue="CME",
    quote_currency="USD",
    tick_size=0.25,
    tick_value=5.00,
    lot_size=1,
    price_precision=2,
    timezone="America/Chicago",
    expiration_rule="quarterly (Mar, Jun, Sep, Dec)",
)

GC = Instrument(
    instrument_id="GC",
    symbol="Gold",
    asset_class="EQUITY_FUTURE",
    venue="COMEX",
    quote_currency="USD",
    tick_size=0.10,
    tick_value=10.00,
    lot_size=1,
    price_precision=2,
    timezone="America/New_York",
    expiration_rule="monthly (Feb, Apr, Jun, Aug, Oct, Dec)",
)


# ─── FX ─────────────────────────────────────────────────────────────────────

EURUSD = Instrument(
    instrument_id="EURUSD",
    symbol="EUR/USD",
    asset_class="FX",
    venue="FXCM",
    quote_currency="USD",
    tick_size=0.0001,
    tick_value=10.00,
    lot_size=100000,
    price_precision=5,
    timezone="UTC",
    currency_conversion_rate=1.0,
)

GBPUSD = Instrument(
    instrument_id="GBPUSD",
    symbol="GBP/USD",
    asset_class="FX",
    venue="FXCM",
    quote_currency="USD",
    tick_size=0.0001,
    tick_value=10.00,
    lot_size=100000,
    price_precision=5,
    timezone="UTC",
)

USDJPY = Instrument(
    instrument_id="USDJPY",
    symbol="USD/JPY",
    asset_class="FX",
    venue="FXCM",
    quote_currency="JPY",
    tick_size=0.01,
    tick_value=6.67,
    lot_size=100000,
    price_precision=3,
    timezone="UTC",
    currency_conversion_rate=0.0067,  # JPY → USD approx
)


# ─── Equity ─────────────────────────────────────────────────────────────────

SPY = Instrument(
    instrument_id="SPY",
    symbol="SPDR S&P 500 ETF",
    asset_class="EQUITY",
    venue="NYSE",
    quote_currency="USD",
    tick_size=0.01,
    tick_value=1.00,
    lot_size=1,
    price_precision=2,
    timezone="America/New_York",
)

QQQ = Instrument(
    instrument_id="QQQ",
    symbol="Invesco QQQ Trust",
    asset_class="EQUITY",
    venue="NASDAQ",
    quote_currency="USD",
    tick_size=0.01,
    tick_value=1.00,
    lot_size=1,
    price_precision=2,
    timezone="America/New_York",
)


# ─── Crypto ─────────────────────────────────────────────────────────────────

BTCUSD = Instrument(
    instrument_id="BTCUSD",
    symbol="Bitcoin/USD",
    asset_class="CRYPTO",
    venue="COINBASE",
    quote_currency="USD",
    tick_size=0.01,
    tick_value=0.01,
    lot_size=0.001,
    price_precision=2,
    timezone="UTC",
    trading_calendar="24x7x365",
)

ETHUSD = Instrument(
    instrument_id="ETHUSD",
    symbol="Ethereum/USD",
    asset_class="CRYPTO",
    venue="COINBASE",
    quote_currency="USD",
    tick_size=0.01,
    tick_value=0.01,
    lot_size=0.01,
    price_precision=2,
    timezone="UTC",
    trading_calendar="24x7x365",
)


# ─── Initial Catalogue ──────────────────────────────────────────────────────

ALL_INSTRUMENTS = [ES, NQ, GC, EURUSD, GBPUSD, USDJPY, SPY, QQQ, BTCUSD, ETHUSD]


def build_initial_catalogue() -> InstrumentCatalogue:
    """Build the initial instrument catalogue with representative fixtures."""
    catalogue = InstrumentCatalogue()
    for instrument in ALL_INSTRUMENTS:
        catalogue.register(instrument)
    return catalogue


# Module-level catalogue for convenience
CATALOGUE = build_initial_catalogue()
