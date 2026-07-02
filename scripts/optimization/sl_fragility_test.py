"""Intraday SL fragility test — measures how often tight SLs get hit intraday.

For each asset, compares:
- Daily-level SL hit rate: close-to-close move exceeds SL distance
- Intraday SL hit rate: 4h bar low breaches SL within the same day

If intraday hit rate > daily hit rate, SL is fragile to intraday wick action.
Tests the new ratio=3.0 configs to verify SL values are safe.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from scripts.backtest.monte_carlo_drawdown import load_pt_sl
from shared.volatility import compute_atr_pct

logger = logging.getLogger("eigencapital.sl_fragility")

RAWDIR = Path("data/raw")
MIN_PERIODS = 20
SL_FRAGILITY_WARN = 1.5  # intraday_hit / daily_hit > 1.5x = fragile
SL_FRAGILITY_CRIT = 4.0  # > 4x = critically fragile (avoid tight SL)


def resolve_ohlcv_path(asset_name: str, suffix: str = "_1d.parquet") -> str | None:
    """Find OHLCV parquet for an asset (handles ^, =X, =F naming)."""
    base = asset_name.replace("^", "").replace("=X", "").replace("=F", "")
    candidates = [
        f"{asset_name}_X{suffix}",
        f"{base}{suffix}",
        f"{base}_F{suffix}",
    ]
    for c in candidates:
        p = RAWDIR / c
        if p.exists():
            return str(p)
    return None


def load_ohlcv(asset_name: str, suffix: str) -> pd.DataFrame | None:
    path = resolve_ohlcv_path(asset_name, suffix)
    if path is None:
        return None
    df = pd.read_parquet(path)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def check_sl_fragility(
    asset: str,
    tp: float,
    sl: float,
    daily: pd.DataFrame,
    intraday: pd.DataFrame | None,
) -> dict:
    """Compare daily vs intraday SL hit rates for a given config."""
    if daily.empty or len(daily) < MIN_PERIODS:
        return {"asset": asset, "error": "insufficient daily data"}

    close = daily["close"]
    atr_pct = compute_atr_pct(daily, period=14)

    daily_sl_hits = 0
    intraday_sl_hits = 0
    total_days = 0

    for i in range(MIN_PERIODS, len(close)):
        entry = close.iloc[i - 1]
        atr = atr_pct.iloc[i]
        if pd.isna(atr) or atr <= 0:
            continue
        sl_dist = sl * atr
        sl_level = entry * (1 - sl_dist)

        total_days += 1

        # Daily check: did the close drop below SL?
        if close.iloc[i] < sl_level:
            daily_sl_hits += 1

        # Intraday check: did any 4h low breach SL?
        if intraday is not None:
            day_open = daily.index[i - 1]
            day_close = daily.index[i]
            iday = intraday.loc[day_open:day_close]
            if not iday.empty and iday["low"].min() < sl_level:
                intraday_sl_hits += 1

    daily_hit_rate = daily_sl_hits / total_days if total_days > 0 else 0
    intraday_hit_rate = intraday_sl_hits / total_days if total_days > 0 else 0

    fragility = intraday_hit_rate / daily_hit_rate if daily_hit_rate > 0 else 1.0

    return {
        "asset": asset,
        "tp_mult": tp,
        "sl_mult": sl,
        "ratio": round(tp / sl, 2),
        "sl_pct": round(atr_pct.iloc[-1] * sl * 100, 2),
        "n_days": total_days,
        "daily_hit_rate": round(daily_hit_rate, 4),
        "intraday_hit_rate": round(intraday_hit_rate, 4),
        "fragility": round(fragility, 2),
        "fragile": fragility > SL_FRAGILITY_WARN,
        "critically_fragile": fragility > SL_FRAGILITY_CRIT,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pt_sl = load_pt_sl()

    results: list[dict] = []
    for name, (tp, sl) in sorted(pt_sl.items()):
        daily = load_ohlcv(name, "_1d.parquet")
        if daily is None:
            logger.warning("  %s: no daily OHLCV data, skipping", name)
            continue

        intraday = load_ohlcv(name, "_4h.parquet")
        result = check_sl_fragility(name, tp, sl, daily, intraday)
        results.append(result)
        logger.info("  %s: done — frag=%.2f", name, result.get("fragility", 0))

    # Report
    print("=" * 100)
    print("  INTRADAY SL FRAGILITY TEST")
    print("=" * 100)
    header = (
        f"{'Asset':12s} {'SL%':>5s} {'Ratio':>6s} "
        f"{'Days':>5s} {'DailyH':>7s} {'IntraH':>7s} "
        f"{'Frag':>5s} {'Status':>8s}"
    )
    print(f"\n  {header}")
    print(f"  {'─' * len(header)}")

    fragile_count = 0
    critical_count = 0
    for r in results:
        if "error" in r:
            print(f"  {r['asset']:12s}  ERROR: {r['error']}")
            continue
        status = "OK"
        if r.get("critically_fragile"):
            status = "CRITICAL"
            critical_count += 1
        elif r.get("fragile"):
            status = "FRAGILE"
            fragile_count += 1
        print(
            f"  {r['asset']:12s} {r['sl_pct']:>5.2f} {r['ratio']:>6.2f} "
            f"{r['n_days']:>5d} {r['daily_hit_rate']:>7.2%} {r['intraday_hit_rate']:>7.2%} "
            f"{r['fragility']:>5.2f} {status:>8s}"
        )

    print(f"\n  {'─' * len(header)}")
    print(f"  OK: {len(results) - fragile_count - critical_count}/{len(results)}")
    print(f"  FRAGILE (>1.5x): {fragile_count}")
    print(f"  CRITICAL (>4x): {critical_count}")
    print(f"\n{'=' * 100}")


if __name__ == "__main__":
    main()
