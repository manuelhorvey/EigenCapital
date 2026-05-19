import os, pickle
import pandas as pd
import numpy as np
from features.contract import FeatureContract
from features.registry import FEATURE_REGISTRY
from labels.triple_barrier import apply_triple_barrier


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize('US/Eastern')
    else:
        df.index = df.index.tz_convert('US/Eastern')
    return df


def compute_macro_derived(macro_df: pd.DataFrame) -> pd.DataFrame:
    m = macro_df.copy()
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['2y_yield_delta_63'] = m['us_2y'].diff(63)
    m['dxy_mom_63'] = m['dxy'].pct_change(63)
    m['dxy_mom_21'] = m['dxy'].pct_change(21)
    m['vix_ma21'] = m['vix'].rolling(21).mean()
    m['vix_delta_5'] = m['vix'].diff(5)
    m['us_jp_10y_spread'] = m['us_10y'] - m['jp_10y']
    m['ca_jp_10y_spread'] = m['ca_10y'] - m['jp_10y']
    m['ca_jp_spread_mom_21'] = m['ca_jp_10y_spread'].diff(21)
    m['ca_jp_spread_mom_5'] = m['ca_jp_10y_spread'].diff(5)
    m['real_yield_delta_63'] = m['real_yield_10y'].diff(63)
    m['breakeven_delta_63'] = m['breakeven_10y'].diff(63)
    return m.iloc[90:]


def compute_label(df: pd.DataFrame, contract: FeatureContract) -> pd.Series:
    if contract.label_type == 'fwd60':
        ret = df['close'].pct_change(contract.label_params['window']).shift(-contract.label_params['window'])
        return ret.apply(
            lambda x: 2 if x > contract.label_params['threshold'] else (0 if x < -contract.label_params['threshold'] else 1)
        ).astype(int).dropna()
    labeled = apply_triple_barrier(df, pt_sl=contract.label_params['pt_sl'],
                                   vertical_barrier=contract.label_params['vertical_barrier'])
    return (labeled['label'] + 1).astype(int)


def build_features(df: pd.DataFrame, macro: pd.DataFrame, ref: pd.DataFrame | None,
                   contract: FeatureContract) -> pd.DataFrame:
    df = _normalize(df)
    if ref is not None:
        ref = _normalize(ref)
    labels = compute_label(df, contract)
    pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labels.index])
    a = macro.reindex(pi, method='ffill')
    a.index = labels.index

    slug = contract.name.lower()
    for w in contract.price_mom_windows:
        a[f'{slug}_mom_{w}'] = df['close'].pct_change(w)

    for w in contract.vs_spy_windows:
        mom = df['close'].pct_change(w)
        spy_mom = ref['close'].pct_change(w) if ref is not None else 0
        a[f'{slug}_vs_spy_{w}'] = mom - spy_mom

    a['label'] = labels
    return a.dropna(subset=list(contract.features) + ['label'])


def compute_training_data(ticker: str, macro: pd.DataFrame, ref: pd.DataFrame,
                          df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, FeatureContract]:
    contract = FEATURE_REGISTRY[ticker]
    features_df = build_features(df, macro, ref, contract)
    return features_df[list(contract.features)], features_df['label'], contract


def compute_inference_features(ticker: str, macro: pd.DataFrame, ref: pd.DataFrame | None,
                               df: pd.DataFrame) -> pd.DataFrame:
    contract = FEATURE_REGISTRY[ticker]
    features_df = build_features(df, macro, ref, contract)
    return features_df[list(contract.features)]


def model_path(ticker: str) -> str:
    contract = FEATURE_REGISTRY[ticker]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'paper_trading', 'models', f'{contract.name}_model.pkl')
