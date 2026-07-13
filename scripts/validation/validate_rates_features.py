#!/usr/bin/env python3
"""Validate Group 3 (rates & carry) features.

Reports:
  1. Yield curve slope computation from ^TNX / ^IRX
  2. Carry differential momentum from rate_diffs
  3. TIPS real rate / breakeven inflation availability
  4. NaN fraction from diff warmup
  5. Correlation with existing alpha features (< 0.90)
  6. Synthetic tests for all computation paths
  7. Leakage walk-through

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_rates_features.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from features.data_fetch import _fetch_macro_batch, _normalize_index
from features.rates_features import (
    compute_all,
    compute_breakeven_features,
    compute_carry_momentum,
    compute_real_rate_features,
    compute_yield_slope,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("validate_rates")


# ── Synthetic tests ────────────────────────────────────────────────────


def test_synthetic() -> None:
    n = 252
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    rng = np.random.default_rng(42)
    tnx = pd.Series(0.040 + rng.normal(0, 0.005, n), index=idx)
    irx = pd.Series(0.005 + rng.normal(0, 0.001, n), index=idx)
    tips = pd.Series(0.015 + rng.normal(0, 0.003, n), index=idx)
    breakeven = tnx - tips
    macro = {"^TNX": tnx, "^IRX": irx, "^TIPS10Y": tips, "^BREKEVEN10Y": breakeven}
    rate_diffs = pd.Series(0.02 + rng.normal(0, 0.002, n), index=idx)

    full = compute_all(macro, rate_diffs, idx)
    assert len(full.columns) == 9, f"expected 9 cols, got {len(full.columns)}"
    assert full.isna().sum().sum() == 0, "NaN should be filled"
    assert full.index.equals(idx), "index alignment"
    logger.info("  full pipeline: ✓ 9 cols, no NaN, aligned")

    partial = compute_all({"^TNX": tnx, "^IRX": irx}, rate_diffs, idx)
    assert len(partial.columns) == 5, f"partial expected 5 cols, got {len(partial.columns)}"
    logger.info("  partial (yield+carry): ✓ 5 cols")

    none_result = compute_all(None, rate_diffs, idx)
    assert len(none_result.columns) == 2, f"no-macro expected 2 cols, got {len(none_result.columns)}"
    assert "rate_diff_5d_chg" in none_result.columns
    logger.info("  no-macro (carry only): ✓ 2 cols")

    # Edge: zero-filled rate diffs for non-FX assets
    zero_rd = pd.Series(0.0, index=idx)
    z = compute_all(macro, zero_rd, idx)
    assert len(z.columns) == 9
    assert z["rate_diff_5d_chg"].iloc[5:].abs().sum() == 0
    logger.info("  zero carry (BTC/GC): ✓ no spurious momentum")


def test_warmup() -> None:
    """Verify NaN warmup periods for diff-based features."""
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    tnx = pd.Series(0.04, index=idx)
    irx = pd.Series(0.01, index=idx)
    ys = compute_yield_slope(tnx, irx)
    assert ys["yield_slope_5d_chg"].iloc[:4].isna().all(), "5d diff warmup"
    assert ys["yield_slope_21d_chg"].iloc[:20].isna().all(), "21d diff warmup"
    logger.info("  warmup periods: ✓ 5d (4 NaN), 21d (20 NaN)")


# ── Live macro data coverage ────────────────────────────────────────────


def check_macro_coverage() -> dict[str, pd.Series]:
    """Check which Group 3 macro series are available from the live pipeline."""
    logger.info("")
    logger.info("Macro Data Availability")
    logger.info("─" * 72)
    macro = _fetch_macro_batch()
    needed = ["^TNX", "^IRX", "^2YR", "^TIPS10Y", "^BREKEVEN10Y"]
    for ticker in needed:
        s = macro.get(ticker, pd.Series(dtype=float))
        status = "✓" if not s.empty else "✗ NOT AVAILABLE"
        logger.info("  %-15s %s  (%d rows, %.4f..%.4f)", ticker, status, len(s),
                     s.min() if not s.empty else 0, s.max() if not s.empty else 0)
    return macro


def check_inference_coverage(macro: dict[str, pd.Series]) -> None:
    """Check feature coverage across the 22-asset portfolio.

    Group 3 yield-slope / real-rate / breakeven features are shared
    (same for all assets).  Carry momentum varies per asset via rate_diff.
    """
    from features.data_fetch import _fetch_macro_batch

    logger.info("")
    logger.info("Feature Coverage")
    logger.info("─" * 72)

    tnx = macro.get("^TNX", pd.Series(dtype=float))
    irx = macro.get("^IRX", pd.Series(dtype=float))
    tips = macro.get("^TIPS10Y", pd.Series(dtype=float))
    be = macro.get("^BREKEVEN10Y", pd.Series(dtype=float))

    logger.info("  Yield curve slope (^TNX - ^IRX):")
    if not tnx.empty and not irx.empty:
        slope = tnx - irx
        logger.info("    last=%.4f (%.1fbp), 5d_chg=%.4f, 21d_chg=%.4f",
                     slope.iloc[-1], slope.iloc[-1] * 10000,
                     slope.diff(5).iloc[-1], slope.diff(21).iloc[-1])
    else:
        logger.info("    ✗ missing TNX or IRX")

    logger.info("  TIPS real rate 10Y:")
    if not tips.empty:
        logger.info("    last=%.4f (%.1fbp), 5d_chg=%.4f, 21d_chg=%.4f",
                     tips.iloc[-1], tips.iloc[-1] * 10000,
                     tips.diff(5).iloc[-1], tips.diff(21).iloc[-1])
    else:
        logger.info("    ✗ missing TIPS10Y")

    logger.info("  Breakeven inflation 10Y:")
    if not be.empty:
        logger.info("    last=%.4f (%.1fbp), 5d_chg=%.4f, 21d_chg=%.4f",
                     be.iloc[-1], be.iloc[-1] * 10000,
                     be.diff(5).iloc[-1], be.diff(21).iloc[-1])
    else:
        logger.info("    ✗ missing BREKEVEN10Y")


# ── Correlation with existing features ──────────────────────────────────


def check_correlation(macro: dict[str, pd.Series]) -> None:
    """Compare Group 3 rate_diff momentum vs existing carry features.

    Uses yfinance directly (no MT5 / store dependency) to fetch asset
    close prices and compute alpha features.  Only tests assets where
    yfinance provides clean close data.
    """
    from features.alpha_features import _compute_shared_features, build_alpha_features

    logger.info("")
    logger.info("─" * 72)
    logger.info("Correlation with existing carry_* features")
    logger.info("─" * 72)

    assets_dir = Path(__file__).resolve().parent.parent.parent / "configs" / "domains" / "assets"
    assets: dict[str, str] = {}
    import yaml
    for f in sorted(assets_dir.glob("*.yaml")):
        name = f.stem
        if name.startswith("_"):
            continue
        with open(f) as fh:
            cfg = yaml.safe_load(fh) or {}
        assets[name] = cfg.get("ticker", name)

    max_corr = 0.0
    max_pair = ("", "", "", 0.0)
    tested = 0

    for name, ticker in assets.items():
        name = str(name); ticker = str(ticker)
        prefix = name.upper()

        # Close prices via yfinance
        df = yf.download(ticker, period="2y", auto_adjust=False, progress=False)
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        prices = df[["Close"]].rename(columns={"Close": name})
        prices.index = _normalize_index(prices.index)

        dxy_s = macro.get("DX-Y.NYB", pd.Series(dtype=float)).reindex(prices.index).ffill().fillna(0.0)
        vix_s = macro.get("^VIX", pd.Series(dtype=float)).reindex(prices.index).ffill().fillna(0.0)
        spx_s = macro.get("^GSPC", pd.Series(dtype=float)).reindex(prices.index).ffill().fillna(0.0)
        commodities = macro.get("CL=F", pd.Series(dtype=float)).to_frame("WTI").reindex(prices.index).ffill().fillna(0.0) if not macro.get("CL=F", pd.Series(dtype=float)).empty else pd.DataFrame()

        # Rate diffs from yields
        base_ccy = prefix[:3]
        quote_ccy = prefix[3:]
        from features.data_fetch import CURRENCY_YIELD_TICKERS, _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS

        if prefix not in _ZERO_RATE_ASSETS and len(prefix) == 6 and base_ccy in _KNOWN_CURRENCIES and quote_ccy in _KNOWN_CURRENCIES:
            base_y = macro.get(CURRENCY_YIELD_TICKERS[base_ccy], pd.Series(dtype=float))
            quote_y = macro.get(CURRENCY_YIELD_TICKERS[quote_ccy], pd.Series(dtype=float))
            rd = (base_y.reindex(prices.index) - quote_y.reindex(prices.index)).ffill()
        else:
            rd = pd.Series(0.0, index=prices.index)
        rate_diffs = pd.DataFrame({name: rd}, index=prices.index)

        ohlcv = pd.DataFrame({"close": prices.iloc[:, 0]})
        shared = _compute_shared_features(dxy=dxy_s, vix=vix_s, spx=spx_s, commodities=commodities, index=prices.index)
        alpha_df = build_alpha_features(
            prices, rate_diffs, dxy=dxy_s, vix=vix_s, spx=spx_s,
            commodities=commodities, shared_features=shared, ohlcv=ohlcv,
        )

        rd_series = rate_diffs[name]
        rates_df = compute_all(macro, rd_series, prices.index)

        common = alpha_df.index.intersection(rates_df.index)
        if len(common) < 5:
            continue
        tested += 1

        carry_cols = [c for c in alpha_df.columns if "carry" in c]
        rate_mom_cols = [c for c in rates_df.columns if "rate_diff" in c]

        for rc in rate_mom_cols:
            r_series = rates_df[rc].dropna()
            if len(r_series) < 5:
                continue
            for cc in carry_cols:
                c_series = alpha_df[cc].dropna()
                ci = r_series.index.intersection(c_series.index)
                if len(ci) < 5:
                    continue
                corr = r_series.loc[ci].corr(c_series.loc[ci], method="spearman")
                if abs(corr) > abs(max_pair[3]):
                    max_pair = (ticker, rc, cc, corr)

    logger.info("  Assets tested with carry features: %d", tested)
    logger.info("  Max |Spearman| with carry_*: %.4f (%s: %s vs %s)",
                 max_pair[3], max_pair[0], max_pair[1], max_pair[2])
    threshold = 0.90
    if abs(max_pair[3]) < threshold:
        logger.info("  ✓ All below %.2f threshold", threshold)
    else:
        logger.warning("  ⚠ Exceeds %.2f threshold — investigate redundancy", threshold)


# ── Leakage ─────────────────────────────────────────────────────────────


def print_leakage() -> None:
    logger.info("")
    logger.info("─" * 72)
    logger.info("Leakage Walk-Through")
    logger.info("─" * 72)
    logger.info("  compute_yield_slope:")
    logger.info("    slope = tnx - irx                    → same-day, independent")
    logger.info("    5d_chg = slope.diff(5)              → uses t-5..t")
    logger.info("    21d_chg = slope.diff(21)            → uses t-21..t")
    logger.info("  compute_carry_momentum:")
    logger.info("    rate_diff_5d_chg = rd.diff(5)       → uses t-5..t")
    logger.info("    rate_diff_21d_chg = rd.diff(21)     → uses t-21..t")
    logger.info("  compute_real_rate_features:")
    logger.info("    real_rate_5d_chg = tips.diff(5)     → uses t-5..t")
    logger.info("    real_rate_21d_chg = tips.diff(21)   → uses t-21..t")
    logger.info("  compute_breakeven_features:")
    logger.info("    breakeven_5d_chg = be.diff(5)       → uses t-5..t")
    logger.info("    breakeven_21d_chg = be.diff(21)     → uses t-21..t")
    logger.info("  ✓ No forward-looking data in any feature")


# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    logger.info("=" * 72)
    logger.info("Group 3 — Rates & Carry Features Validation")
    logger.info("=" * 72)

    logger.info("")
    logger.info("Synthetic Data Tests")
    logger.info("─" * 72)
    test_synthetic()
    test_warmup()

    macro = check_macro_coverage()
    check_inference_coverage(macro)
    check_correlation(macro)
    print_leakage()

    # Verdict
    tnx_ok = not macro.get("^TNX", pd.Series(dtype=float)).empty
    irx_ok = not macro.get("^IRX", pd.Series(dtype=float)).empty
    tips_ok = not macro.get("^TIPS10Y", pd.Series(dtype=float)).empty
    be_ok = not macro.get("^BREKEVEN10Y", pd.Series(dtype=float)).empty
    yield_ok = tnx_ok and irx_ok

    logger.info("")
    logger.info("=" * 72)
    if yield_ok and tips_ok and be_ok:
        logger.info("VERDICT: GO — all macro series available")
    elif yield_ok and not tips_ok and not be_ok:
        logger.info("VERDICT: PARTIAL — yield slope ✓, TIPS/BE ✗ (FRED API key may be needed)")
    else:
        logger.info("VERDICT: NO-GO — missing macro data")
    logger.info("  Yield curve:   %s", "✓" if yield_ok else "✗")
    logger.info("  TIPS real rate: %s", "✓" if tips_ok else "✗ (needs FRED_API_KEY)")
    logger.info("  Breakeven:     %s", "✓" if be_ok else "✗ (needs FRED_API_KEY)")
    logger.info("=" * 72)


if __name__ == "__main__":
    main()
