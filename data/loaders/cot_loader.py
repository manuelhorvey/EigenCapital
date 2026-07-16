import pandas as pd
import numpy as np

FX_COT_CONTRACTS = {
    "EURUSD": "EURO FX",
    "GBPUSD": "BRITISH POUND",
    "USDJPY": "JAPANESE YEN",
    "AUDUSD": "AUSTRALIAN DOLLAR",
    "USDCAD": "CANADIAN DOLLAR",
    "USDCHF": "SWISS FRANC",
    "NZDUSD": "NEW ZEALAND DOLLAR",
    "MXNUSD": "MEXICAN PESO",
}


def load_cot_weekly(
    path: str = "data/processed/trade_data/cot_raw.parquet",
) -> pd.DataFrame:
    return pd.read_parquet(path)


def get_contract_series(
    cot_df: pd.DataFrame,
    symbol: str,
) -> pd.Series | None:
    contract_name = FX_COT_CONTRACTS.get(symbol.upper())
    if contract_name is None:
        return None

    mask = cot_df["Market_and_Exchange_Names"].str.match(
        rf"{contract_name}\s*-", case=False, na=False
    )
    series = cot_df[mask].set_index("date").sort_index()
    series.index.name = "date"
    series = series[~series.index.duplicated(keep="last")]
    return series


def align_cot_to_daily(
    cot_weekly: pd.DataFrame,
    price_index: pd.DatetimeIndex,
    release_lag_days: int = 3,
) -> pd.DataFrame:
    """
    COT positions are as of Tuesday close, released Friday afternoon.
    Shift by release_lag_days before forward-filling to prevent look-ahead.
    """
    cot_shifted = cot_weekly.copy()
    cot_shifted.index = cot_weekly.index + pd.Timedelta(days=release_lag_days)
    return cot_shifted.reindex(price_index, method="ffill")
