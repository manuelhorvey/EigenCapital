import pandas as pd
import numpy as np
from datetime import datetime

FRED_SERIES = {
    'fed_funds':      'FEDFUNDS',
    'ecb_rate':       'ECBDFR',
    'us_2y':          'DGS2',
    'us_10y':         'DGS10',
    'breakeven_10y':  'T10YIE',
    'real_yield_10y': 'DFII10',
    'dxy':            'DTWEXBGS',
    'vix':            'VIXCLS',
    'baa_spread':     'BAA10Y',
    'jp_10y':         'IRLTLT01JPM156N',
    'de_10y':         'IRLTLT01DEM156N',
    'gb_10y':         'IRLTLT01GBM156N',
    'ca_10y':         'IRLTLT01CAM156N',
    'au_10y':         'IRLTLT01AUM156N',
}

MACRO_FEATURES = [
    'rate_diff',
    'rate_diff_delta_3m',
    'real_yield_10y',
    'yield_slope',
    'dxy_mom_21',
    'dxy_mom_63',
    'fed_funds_delta_3m',
]


RESAMPLE_FREQ = 'D'


def _fill_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    daily_index = pd.date_range(df.index.min(), df.index.max(), freq=RESAMPLE_FREQ)
    return df.reindex(daily_index).ffill()


def compute_derived_features(macro: pd.DataFrame) -> pd.DataFrame:
    daily = _fill_to_daily(macro)

    daily['rate_diff'] = daily['fed_funds'] - daily['ecb_rate']

    daily['yield_slope'] = daily['us_10y'] - daily['us_2y']

    daily['dxy_mom_21'] = daily['dxy'].pct_change(21, fill_method=None)
    daily['dxy_mom_63'] = daily['dxy'].pct_change(63, fill_method=None)

    CALENDAR_DAYS_3M = 90
    daily['fed_funds_delta_3m'] = daily['fed_funds'].diff(CALENDAR_DAYS_3M)
    daily['rate_diff_delta_3m'] = daily['rate_diff'].diff(CALENDAR_DAYS_3M)

    return daily


def align_macro_to_daily(macro_df: pd.DataFrame,
                          price_index: pd.DatetimeIndex) -> pd.DataFrame:
    if hasattr(price_index, 'tz') and price_index.tz is not None:
        if macro_df.index.tz is None:
            macro_df = macro_df.tz_localize(price_index.tz)
        else:
            macro_df = macro_df.tz_convert(price_index.tz)
    result = macro_df.reindex(price_index, method='ffill')
    result.index = result.index.normalize()
    return result


def load_macro_features(price_index: pd.DatetimeIndex = None,
                        path: str = 'data/processed/macro_factors.parquet') -> pd.DataFrame:
    raw = pd.read_parquet(path)

    derived = compute_derived_features(raw)

    if price_index is not None:
        derived = align_macro_to_daily(derived, price_index)

    return derived

MACRO_FEATURES = [
    'rate_diff',
    'rate_diff_delta_3m',
    'real_yield_10y',
    'yield_slope',
    'dxy_mom_21',
    'dxy_mom_63',
    'fed_funds_delta_3m',
]


def correlation_sanity_check(macro: pd.DataFrame,
                             eurusd_returns: pd.Series,
                             start: str = '2022',
                             end: str = '2024') -> pd.DataFrame:
    df = macro.copy()
    df['ret_21'] = eurusd_returns.rolling(21).sum()

    subset = df[start:end].dropna(subset=['rate_diff', 'rate_diff_delta_3m', 'ret_21'])

    corr = subset[['rate_diff', 'rate_diff_delta_3m', 'ret_21']].corr()
    return corr
