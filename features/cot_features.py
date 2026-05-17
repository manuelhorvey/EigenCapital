import pandas as pd
import numpy as np


def cot_index(net_position: pd.Series, window: int = 52) -> pd.Series:
    roll_min = net_position.rolling(window).min()
    roll_max = net_position.rolling(window).max()
    return (net_position - roll_min) / (roll_max - roll_min + 1e-9)


def compute_net_positions(series: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=series.index)
    df["lev_net"] = (
        series["Lev_Money_Positions_Long_All"]
        - series["Lev_Money_Positions_Short_All"]
    )
    df["dealer_net"] = (
        series["Dealer_Positions_Long_All"]
        - series["Dealer_Positions_Short_All"]
    )
    df["asset_mgr_net"] = (
        series["Asset_Mgr_Positions_Long_All"]
        - series["Asset_Mgr_Positions_Short_All"]
    )
    df["open_interest"] = series["Open_Interest_All"]
    return df


def build_cot_features(
    series: pd.DataFrame,
    cot_index_window: int = 52,
    extreme_percentile: float = 0.10,
) -> pd.DataFrame:
    net = compute_net_positions(series)

    features = pd.DataFrame(index=net.index)

    features["lev_net"] = net["lev_net"]
    features["dealer_net"] = net["dealer_net"]
    features["asset_mgr_net"] = net["asset_mgr_net"]

    features["lev_net_cot_index"] = cot_index(net["lev_net"], cot_index_window)
    features["dealer_net_cot_index"] = cot_index(net["dealer_net"], cot_index_window)
    features["asset_mgr_net_cot_index"] = cot_index(net["asset_mgr_net"], cot_index_window)

    features["lev_net_change_1w"] = net["lev_net"].diff(1)
    features["lev_net_change_4w"] = net["lev_net"].diff(4)

    features["dealer_net_change_1w"] = net["dealer_net"].diff(1)
    features["dealer_net_change_4w"] = net["dealer_net"].diff(4)

    features["asset_mgr_net_change_1w"] = net["asset_mgr_net"].diff(1)
    features["asset_mgr_net_change_4w"] = net["asset_mgr_net"].diff(4)

    total_rept_long = series["Asset_Mgr_Positions_Long_All"]
    total_rept_long += series["Dealer_Positions_Long_All"]
    total_rept_long += series["Lev_Money_Positions_Long_All"]
    total_rept_long += series["Other_Rept_Positions_Long_All"]
    features["pct_long_lev"] = (
        series["Lev_Money_Positions_Long_All"] / total_rept_long
    )
    features["pct_short_lev"] = (
        series["Lev_Money_Positions_Short_All"] / total_rept_long
    )

    denom = net["asset_mgr_net"].abs() + net["lev_net"].abs() + 1e-9
    features["commercial_to_lev_ratio"] = net["asset_mgr_net"] / denom

    features["positioning_extreme"] = (
        features["lev_net_cot_index"]
        .pipe(
            lambda x: (x < extreme_percentile) | (x > (1 - extreme_percentile))
        )
        .astype(int)
    )

    return features


EURUSD_COT_FEATURES = [
    "lev_net_cot_index",
    "lev_net_change_4w",
    "commercial_to_lev_ratio",
    "positioning_extreme",
]
