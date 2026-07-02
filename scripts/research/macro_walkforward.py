import pandas as pd

from features.publication_lags import apply_publication_lags
from models.macro_only import FEATURES, MacroOnlyModel
from signals.simple_threshold import THRESHOLD, generate_signals

WF_CONFIG = {
    "train_years": 3,
    "test_years": 1,
    "step_years": 1,
    "min_trades": 20,
}

ASSETS = ["XLF"]


def load_data():
    xlf = pd.read_parquet("data/raw/XLF_1d.parquet")
    spy = pd.read_parquet("data/raw/SPY_1d.parquet")
    macro_raw = pd.read_parquet("data/processed/macro_factors.parquet")
    macro_raw = apply_publication_lags(macro_raw)

    def _strip_tz(idx):
        if hasattr(idx, "tz") and idx.tz is not None:
            return idx.tz_localize(None)
        return idx

    if hasattr(xlf.index, "tz") and xlf.index.tz is not None:
        xlf.index = xlf.index.tz_localize(None)
    if hasattr(spy.index, "tz") and spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    xlf_idx = xlf.index.normalize()
    macro_daily = macro_raw.copy()
    macro_daily.index = _strip_tz(pd.DatetimeIndex(macro_daily.index).normalize())
    macro_daily = macro_daily.ffill()
    macro_daily = macro_daily.reindex(xlf_idx, method="ffill")

    macro_daily["rate_diff"] = macro_daily["fed_funds"] - macro_daily["ecb_rate"]
    macro_daily["2y_yield_delta_63"] = macro_daily["us_2y"].diff(63)

    spy_idx = spy.index.normalize()
    close_xlf = xlf["close"].reindex(xlf_idx, method="ffill")
    close_spy = spy["Close"].reindex(spy_idx, method="ffill")
    if isinstance(close_spy, pd.DataFrame):
        close_spy = close_spy.iloc[:, 0]
    common = close_xlf.index.intersection(close_spy.index)
    close_xlf = close_xlf.reindex(common, method="ffill")
    close_spy = close_spy.reindex(common, method="ffill")

    macro_daily["xlf_mom_63"] = close_xlf.pct_change(63)
    macro_daily["xlf_vs_spy_63"] = close_xlf.pct_change(63) - close_spy.pct_change(63)

    df = macro_daily[FEATURES].copy()
    df["close"] = close_xlf
    df["returns"] = close_xlf.pct_change()
    df = df.dropna()
    return df


def compute_labels(df: pd.DataFrame) -> pd.Series:
    forward_ret = df["returns"].shift(-1)
    labels = pd.Series(1, index=df.index)
    labels[forward_ret > 0.002] = 2
    labels[forward_ret < -0.002] = 0
    return labels


def calculate_expectancy(trades: pd.DataFrame) -> dict:
    if len(trades) == 0:
        return {"expectancy": 0, "n_trades": 0, "profit_factor": 0, "win_rate": 0}
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]
    wins["pnl"].mean() if len(wins) > 0 else 0
    abs(losses["pnl"].mean()) if len(losses) > 0 else 0
    pf = (wins["pnl"].sum() / abs(losses["pnl"].sum())) if len(losses) > 0 else float("inf")
    return {
        "expectancy": trades["pnl"].mean(),
        "n_trades": len(trades),
        "profit_factor": pf,
        "win_rate": len(wins) / len(trades) if len(trades) > 0 else 0,
    }


def main():
    df = load_data()
    years = sorted(df.index.year.unique())
    print(f"\n{'=' * 60}")
    print("MACRO-ONLY WALKFORWARD")
    print(f"{'=' * 60}")
    print("Asset: XLF")
    print(f"Features: {FEATURES}")
    print(f"Threshold: {THRESHOLD}")
    print(f"Data: {df.index.min().date()} to {df.index.max().date()} ({len(df)} rows)")
    print(f"{'=' * 60}")
    print(f"{'Window':<12} {'Trades':<8} {'PF':<8} {'Expectancy':<12} {'WinRate':<8}")
    print(f"{'-' * 48}")

    rows = []
    for test_year in range(years[0] + WF_CONFIG["train_years"], years[-1] + 1):
        train_end = test_year - 1
        train_start = test_year - WF_CONFIG["train_years"]
        train_mask = (df.index.year >= train_start) & (df.index.year <= train_end)
        test_mask = df.index.year == test_year
        if test_mask.sum() < 20:
            continue

        X_train = df.loc[train_mask]
        X_test = df.loc[test_mask]
        y_train = compute_labels(X_train)
        compute_labels(X_test)

        split = int(len(X_train) * 0.8)
        X_val = X_train.iloc[split:]
        y_val = y_train.iloc[split:]
        X_train_fit = X_train.iloc[:split]
        y_train_fit = y_train.iloc[:split]

        if X_val[FEATURES].isnull().any().any() or X_train_fit[FEATURES].isnull().any().any():
            continue

        model = MacroOnlyModel()
        model.fit(X_train_fit, y_train_fit, X_val, y_val)

        probs = model.predict_proba(X_test)
        signals = generate_signals(probs)

        trades = X_test.copy()
        trades["signal"] = signals
        trades["pnl"] = trades["signal"] * trades["returns"].shift(-1).fillna(0)
        trades = trades[trades["signal"] != 0]

        metrics = calculate_expectancy(trades)

        window_label = f"{train_start}-{test_year}"
        print(
            f"{window_label:<12} {metrics['n_trades']:<8} {metrics['profit_factor']:<8.2f} {metrics['expectancy']:<+12.6f} {metrics['win_rate']:<8.2%}"  # noqa: E501
        )  # noqa: E501

        rows.append(
            {
                "window": window_label,
                "test_year": test_year,
                "trades": metrics["n_trades"],
                "pf": metrics["profit_factor"],
                "expectancy": metrics["expectancy"],
                "win_rate": metrics["win_rate"],
            }
        )

    print(f"{'=' * 48}")
    results = pd.DataFrame(rows)
    print("\nSummary:")
    print(f"  Windows: {len(results)}")
    print(f"  Avg PF: {results['pf'].mean():.4f}")
    print(f"  Avg Expectancy: {results['expectancy'].mean():+.6f}")
    print(f"  Total Trades: {results['trades'].sum()}")
    print(f"  Positive PF windows: {(results['pf'] > 1).sum()}/{len(results)}")
    positive_2022_2024 = results[results["test_year"].isin([2022, 2023, 2024])]
    if len(positive_2022_2024) > 0:
        print("\n2022-2024:")
        for _, r in positive_2022_2024.iterrows():
            print(f"  {r['window']}: PF={r['pf']:.2f}, Expectancy={r['expectancy']:+.6f}, Trades={r['trades']}")
        all_pos = (positive_2022_2024["pf"] > 1).all()
        print(f"  All positive PF: {'YES' if all_pos else 'NO'}")

    return results


if __name__ == "__main__":
    main()
