from features.contract import FeatureContract

FEATURE_REGISTRY: dict[str, FeatureContract] = {
    "BTC-USD": FeatureContract(
        ticker="BTC-USD", name="BTC",
        label_type="tb20",
        label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
        macro_filters=("rate_diff", "2y_yield_delta_63"),
        price_mom_windows=(63,),
        vs_spy_windows=(63,),
    ),
    "GC=F": FeatureContract(
        ticker="GC=F", name="GC",
        label_type="fwd60",
        label_params={"window": 60, "threshold": 0.02},
        macro_filters=("real_yield_delta_63", "breakeven_delta_63", "dxy_mom_63"),
        price_mom_windows=(63,),
        vs_spy_windows=(),
    ),
    "CADJPY=X": FeatureContract(
        ticker="CADJPY=X", name="CADJPY",
        label_type="fwd60",
        label_params={"window": 60, "threshold": 0.02},
        macro_filters=("ca_jp_spread_mom_5", "ca_jp_spread_mom_21", "vix_ma21"),
        price_mom_windows=(21,),
        vs_spy_windows=(),
    ),
    "NZDJPY=X": FeatureContract(
        ticker="NZDJPY=X", name="NZDJPY",
        label_type="tb20",
        label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
        macro_filters=("vix_ma21", "vix_delta_5", "us_jp_10y_spread"),
        price_mom_windows=(21,),
        vs_spy_windows=(),
    ),
    "USDCAD=X": FeatureContract(
        ticker="USDCAD=X", name="USDCAD",
        label_type="tb20",
        label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
        macro_filters=("rate_diff", "dxy_mom_21", "vix_ma21"),
        price_mom_windows=(21,),
        vs_spy_windows=(),
    ),
    "EURAUD=X": FeatureContract(
        ticker="EURAUD=X", name="EURAUD",
        label_type="tb20",
        label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
        macro_filters=("rate_diff", "dxy_mom_21", "vix_ma21"),
        price_mom_windows=(21,),
        vs_spy_windows=(),
    ),
}
