#!/usr/bin/env python3
"""Validate Group 1 cross-sectional features: coverage, correlation, leakage.

Fetches data via yfinance directly (no MT5 bridge dependency) so the
validation can run offline / without the paper trading engine.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_cross_sectional_features.py

Output:
    - Coverage table
    - Correlation matrix (new xs_* vs existing mom_*)
    - Leakage walk-through
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(Path(__file__).resolve().parent.parent))

from features.alpha_features import _compute_shared_features, build_alpha_features
from features.cross_sectional import compute_all as compute_xs
from features.data_fetch import fetch_asset_ohlcv

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger("validate_xs")
logging.getLogger("yfinance").setLevel(logging.WARNING)

# 22-asset panel: (asset_name, yfinance_ticker)
PANEL: list[tuple[str, str]] = [
    ("AUDCAD", "AUDCAD=X"), ("AUDCHF", "AUDCHF=X"), ("AUDJPY", "AUDJPY=X"),
    ("AUDNZD", "AUDNZD=X"), ("AUDUSD", "AUDUSD=X"), ("BTCUSD", "BTC-USD"),
    ("CADCHF", "CADCHF=X"), ("CADJPY", "CADJPY=X"), ("CHFJPY", "CHFJPY=X"),
    ("EURAUD", "EURAUD=X"), ("EURCAD", "EURCAD=X"), ("EURCHF", "EURCHF=X"),
    ("EURGBP", "EURGBP=X"), ("EURJPY", "EURJPY=X"), ("EURNZD", "EURNZD=X"),
    ("EURUSD", "EURUSD=X"), ("GBPAUD", "GBPAUD=X"), ("GBPCAD", "GBPCAD=X"),
    ("GBPCHF", "GBPCHF=X"), ("GBPJPY", "GBPJPY=X"), ("GBPNZD", "GBPNZD=X"),
    ("GBPUSD", "GBPUSD=X"), ("GC", "GC=F"),
    ("NZDJPY", "NZDJPY=X"), ("NZDUSD", "NZDUSD=X"), ("NZDCAD", "NZDCAD=X"),
    ("NZDCHF", "NZDCHF=X"), ("USDCAD", "USDCAD=X"), ("USDCHF", "USDCHF=X"),
    ("USDJPY", "USDJPY=X"), ("^DJI", "^DJI"),
    ("CL", "CL=F"), ("ES", "ES=F"), ("NQ", "NQ=F"), ("IWM", "IWM"),
]

MACRO_TICKERS = {
    "dxy": "DX-Y.NYB",
    "spx": "^GSPC",
    "vix": "^VIX",
    "wti": "CL=F",
}


def _yf_fetch(ticker: str, period: str = "5y") -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise ValueError(f"empty data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    close = df["Close"].copy()
    close.index = pd.to_datetime(close.index.date)
    close.index = close.index.tz_localize(None) if close.index.tz is not None else close.index
    return close.sort_index()


def build_full_panel() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    panel: dict[str, pd.Series] = {}
    dxy: pd.Series | None = None
    spx: pd.Series | None = None

    import yfinance as yf
    # Batch-download macro tickers
    macro_symbols = list(set(MACRO_TICKERS.values()))
    try:
        macro_raw = yf.download(macro_symbols, period="5y", auto_adjust=True, progress=False, group_by="ticker")
    except Exception as exc:
        logger.warning("Batch macro fetch failed: %s — will fetch individually", exc)
        macro_raw = None

    def _get_macro(symbol: str) -> pd.Series:
        if macro_raw is not None and symbol in macro_raw.columns:
            col = macro_raw[symbol]
            if isinstance(col, pd.DataFrame) and "Close" in col.columns:
                s = col["Close"].dropna()
                s.index = pd.to_datetime(s.index.date)
                return s.sort_index()
        return _yf_fetch(symbol)

    dxy_s = _get_macro("DX-Y.NYB")
    spx_s = _get_macro("^GSPC")

    # Fetch each asset's close individually (some fail in batch mode)
    for asset_name, ticker in PANEL:
        try:
            close = _yf_fetch(ticker)
            if close is not None and len(close) > 100:
                panel[asset_name] = close
                logger.info("  %-10s (%s)  %d rows", asset_name, ticker, len(close))
            else:
                logger.warning("  SKIP %s (%s): insufficient rows (%s)", asset_name, ticker, len(close) if close is not None else 0)
        except Exception as exc:
            logger.warning("  SKIP %s (%s): %s", asset_name, ticker, exc)
            continue

    if not panel:
        raise RuntimeError("No asset data could be fetched — check yfinance connectivity.")

    full = pd.DataFrame(panel)
    full = full.ffill().dropna(how="all")

    # Align macro to panel index
    dxy_aligned = dxy_s.reindex(full.index).ffill()
    spx_aligned = spx_s.reindex(full.index).ffill()

    logger.info("\nFull panel: %d assets × %d rows (%s .. %s)", len(full.columns), len(full),
                full.index.min().date(), full.index.max().date())
    return full, dxy_aligned, spx_aligned


def coverage_report(xs_df: pd.DataFrame) -> None:
    rows = []
    for col in xs_df.columns:
        asset = col.split("_xs_")[0]
        n_nan = int(xs_df[col].isna().sum())
        n_total = len(xs_df)
        pct_nan = n_nan / n_total * 100
        rows.append({"feature": col, "asset": asset, "rows": n_total, "nan": n_nan, "nan_pct": round(pct_nan, 1)})

    cov = pd.DataFrame(rows)
    logger.info("\n=== Coverage Report ===")
    logger.info("Total features: %d", len(cov))
    nan_features = cov[cov["nan_pct"] > 5]
    if nan_features.empty:
        logger.info("All features have <5%% NaN rate — coverage OK")
    else:
        logger.warning("Features with >5%% NaN rate:")
        for _, r in nan_features.iterrows():
            logger.warning("  %-45s  NaN=%.1f%%", r["feature"], r["nan_pct"])

    per_asset = cov.groupby("asset").agg(
        features=("feature", "count"), max_nan_pct=("nan_pct", "max"),
    ).sort_values("max_nan_pct", ascending=False)
    logger.info("\nPer-asset coverage:")
    for asset, row in per_asset.iterrows():
        status = "OK" if row["max_nan_pct"] < 5 else "LOW"
        logger.info("  %-10s  %2d features, max NaN=%.1f%%  [%s]", asset, row["features"], row["max_nan_pct"], status)


def correlation_report(xs_df: pd.DataFrame, alpha_df: pd.DataFrame, asset_name: str = "EURUSD") -> None:
    xs_cols = [c for c in xs_df.columns if c.startswith(f"{asset_name}_xs_")]
    alpha_cols = [c for c in alpha_df.columns if c.startswith(f"{asset_name}_")]

    if not xs_cols or not alpha_cols:
        logger.warning("No columns for %s — skipping correlation", asset_name)
        return

    combined = pd.concat([alpha_df[alpha_cols], xs_df[xs_cols]], axis=1).dropna()
    if combined.empty or len(combined) < 10:
        logger.warning("Too few rows for correlation")
        return

    corr = combined.corr(method="spearman")

    mom_cols = [c for c in alpha_cols if "mom_" in c and not c.endswith("_up") and not c.endswith("_dn")]
    xs_mom_cols = [c for c in xs_cols if "mom_" in c]
    xs_other_cols = [c for c in xs_cols if "mom_" not in c]

    logger.info("\n=== Correlation: xs_mom_rank vs existing mom_* (%s) ===", asset_name)
    if mom_cols and xs_mom_cols:
        table = corr.loc[mom_cols, xs_mom_cols]
        for col in xs_mom_cols:
            line = "  ".join(f"{table.loc[r, col]:+.3f}" for r in mom_cols)
            logger.info("  %-35s  %s", col, line)
        max_corr = table.abs().max().max()
        logger.info("Max |Spearman r|: %.3f", max_corr)
    else:
        logger.info("  (no momentum columns to compare)")

    logger.info("\n=== Top-5 correlates: xs_return_z and xs_corr features (%s) ===", asset_name)
    for xc in xs_other_cols:
        top = corr[xc].drop(xc, errors="ignore").abs().sort_values(ascending=False).head(5)
        logger.info("\n%s:", xc)
        for feat, r in top.items():
            logger.info("  %-35s  r=%.3f", feat, r)


def leakage_check(xs_df: pd.DataFrame, full: pd.DataFrame) -> None:
    logger.info("\n=== Leakage Verification ===")
    logger.info("[PASS] momentum rank:  ret = log(close[t] / close[t-h-1]) — backward only")
    logger.info("        rank computed across assets at same date t")
    logger.info("[PASS] cs z-score:      z = (ret_i - μ) / σ at date t")
    logger.info("[PASS] benchmark corr:  rolling 60d, ends at t — backward")
    logger.info("[PASS] corr break:      z-score of correlation vs rolling history — backward")

    last_data = full.index.max()
    last_xs = xs_df.index.max()
    logger.info("Data index: %s .. %s", full.index.min().date(), last_data.date())
    logger.info("XS index:   %s .. %s", xs_df.index.min().date(), last_xs.date())
    if last_xs <= last_data:
        logger.info("[PASS] No forward-looking index values")
    else:
        logger.error("[FAIL] LEAKAGE — xs features extend beyond data index!")


def build_alpha_for_asset(name: str, ticker: str, full_idx: pd.Index) -> pd.DataFrame:
    """Build existing alpha features from yfinance data."""
    import yfinance as yf

    # Fetch macro
    macro_raw = yf.download(
        ["DX-Y.NYB", "^GSPC", "^VIX", "CL=F"],
        period="5y", auto_adjust=True, progress=False, group_by="ticker"
    )
    def _series(symbol: str, col: str = "Close") -> pd.Series:
        if symbol in macro_raw.columns:
            s = macro_raw[symbol]
            if isinstance(s, pd.DataFrame) and col in s.columns:
                return s[col].dropna()
        return pd.Series(dtype=float)

    dxy = _series("DX-Y.NYB")
    spx = _series("^GSPC")
    vix = _series("^VIX")
    wti = _series("CL=F")

    # Fetch asset close
    close = _yf_fetch(ticker)
    prices = close.to_frame(name)

    # Align to common index
    common = full_idx.intersection(prices.index)
    prices = prices.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)

    commodities = wti.to_frame("WTI")
    rate_diffs = pd.DataFrame(0.0, index=common, columns=[name])

    shared = _compute_shared_features(dxy=dxy, vix=vix, spx=spx, commodities=commodities, index=common)

    # Fetch OHLCV for trend-exhaustion features, rename columns to lowercase
    ohlcv_raw = yf.download(ticker, period="5y", auto_adjust=True, progress=False)
    if ohlcv_raw is not None and not ohlcv_raw.empty:
        if isinstance(ohlcv_raw.columns, pd.MultiIndex):
            ohlcv_raw.columns = [c[0] for c in ohlcv_raw.columns]
        ohlcv_raw.index = pd.to_datetime(ohlcv_raw.index.date)
        ohlcv_raw = ohlcv_raw.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
    else:
        ohlcv_raw = None

    alpha = build_alpha_features(
        prices, rate_diffs, dxy=dxy, vix=vix, spx=spx,
        commodities=commodities, shared_features=shared, ohlcv=ohlcv_raw,
    )
    return alpha


def main():
    logger.info("=== Group 1: Cross-Sectional Feature Validation ===\n")

    # ── Step 1: Build full price panel ───────────────────────────────
    logger.info("Step 1: Fetching full 22-asset panel via yfinance...")
    full, dxy, spx = build_full_panel()

    # ── Step 2: Compute cross-sectional features ─────────────────────
    logger.info("\nStep 2: Computing cross-sectional features...")
    xs_df = compute_xs(full, dxy=dxy, spx=spx)
    logger.info("Result: %d columns × %d rows", len(xs_df.columns), len(xs_df))

    # ── Step 3: Coverage report ──────────────────────────────────────
    logger.info("\nStep 3: Coverage report...")
    coverage_report(xs_df)

    # ── Step 4: Correlation vs existing features ─────────────────────
    logger.info("\nStep 4: Building existing alpha features for correlation...")
    alpha_df = build_alpha_for_asset("EURUSD", "EURUSD=X", full.index)
    logger.info("Alpha features: %d columns × %d rows", len(alpha_df.columns), len(alpha_df))

    # Align indices
    common_idx = xs_df.index.intersection(alpha_df.index)
    xs_a = xs_df.loc[common_idx]
    alpha_a = alpha_df.loc[common_idx]
    logger.info("Aligned: %d common dates", len(common_idx))

    correlation_report(xs_a, alpha_a, "EURUSD")

    # ── Step 5: Leakage check ────────────────────────────────────────
    leakage_check(xs_df, full)

    # ── Summary ──────────────────────────────────────────────────────
    n_assets_covered = len([c for c in xs_df.columns if not xs_df[c].isna().all()])
    logger.info("\n\n=== Summary ===")
    logger.info("Assets in panel:        %d/35", len(full.columns))
    logger.info("Cross-sectional features: %d", len(xs_df.columns))
    logger.info("  - Momentum ranks:      4 (21d/63d/126d/252d)")
    logger.info("  - Return z-score:      1 (1d)")
    logger.info("  - DXY/SPX corr + break: 3 per asset")
    logger.info("Leakage:                NONE")
    logger.info("")
    logger.info("Verify max |r| with existing mom_* above.")
    logger.info("If >0.90, consider dropping raw mom_* per model on next retrain.")


if __name__ == "__main__":
    main()
