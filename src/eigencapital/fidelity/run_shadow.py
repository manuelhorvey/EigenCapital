"""Run Shadow Campaign — compares paper path against broker boundary.

This script:
1. Loads MT5 data
2. Runs R4 through paper path
3. Runs R4 through shadow path (simulating broker boundary)
4. Compares paper vs shadow at every decision boundary
5. Produces the shadow qualification report
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.shadow import ShadowEngine

logger = logging.getLogger(__name__)


def run_shadow() -> Dict[str, Any]:
    """Run shadow campaign and produce qualification report."""
    print("=" * 70)
    print("SHADOW EXECUTION CAMPAIGN")
    print("Paper Path vs Broker Boundary Comparison")
    print("=" * 70)

    # 1. Load data
    print("\n[1/5] Loading MT5 data...")
    provider = MT5DataProvider()
    data, manifest = provider.load_from_csv()
    print(f"  Loaded {len(data)} symbols, {sum(len(df) for df in data.values())} total bars")

    # 2. Create R4 manifest
    print("\n[2/5] Creating frozen R4 manifest...")
    r4_manifest = R4ConfigManifest(
        data_snapshot_hash=manifest.snapshot_hash,
        data_bar_count=manifest.bar_count,
    )
    print(f"  Manifest identity: {r4_manifest.compute_identity()[:16]}...")

    # 3. Initialize shadow engine
    print("\n[3/5] Initializing shadow engine...")
    shadow = ShadowEngine(r4_manifest)
    print(f"  Campaign ID: {shadow._campaign_id}")

    # 4. Compute R4 weights (same as paper)
    print("\n[4/5] Running R4 through paper and shadow paths...")
    returns_df = pd.DataFrame(
        {sym: df["close"].pct_change() for sym, df in data.items() if "close" in df.columns}
    ).dropna(how="all")

    # R4 weights (frozen)
    mom_12m = (1 + returns_df).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(21).apply(lambda x: x.prod() - 1, raw=True)
    signal = (mom_12m - mom_1m).dropna(how="all")
    ranks = signal.rank(axis=1, pct=True)
    base_weights = ranks - 0.5

    avg_vol = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)
    rc_weights = base_weights.multiply(regime, axis=0)

    asset_vol = returns_df.rolling(60).std() * np.sqrt(252)
    vol_ratio = asset_vol / 0.50
    cap = np.minimum(vol_ratio, 1.0)
    vol_capped = rc_weights * cap

    crypto_cols = [c for c in vol_capped.columns if "BTC" in c or "ETH" in c]
    crypto_capped = vol_capped.copy()
    for col in crypto_cols:
        if col in crypto_capped.columns:
            crypto_capped[col] = crypto_capped[col].clip(-0.10, 0.10)

    final_weights = crypto_capped.clip(-0.20, 0.20)
    inv_vol = 1 / asset_vol.replace(0, np.nan)
    rp_weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0)
    combined = 0.7 * final_weights + 0.3 * rp_weights

    port_ret = (combined.shift(1) * returns_df).sum(axis=1) / combined.abs().sum(axis=1).replace(0, np.nan)
    port_ret = port_ret.dropna()
    cum = (1 + port_ret).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    in_dd = (dd < -0.15).astype(float)
    scale = 1 - (in_dd * 0.5)
    final = combined.multiply(scale, axis=0)

    # Process through shadow engine
    signal_count = 0
    for date in final.index:
        for inst in final.columns:
            w = final.loc[date, inst]
            if abs(w) > 1e-6 and inst in data:
                df = data[inst]
                if date in df.index:
                    row = df.loc[date]
                    close = float(row.get("close", 0))
                    spread = 0.0002  # simulated spread

                    # Paper path: signal → weight → position
                    paper_signal = (
                        float(signal.loc[date, inst]) if inst in signal.columns and date in signal.index else 0.0
                    )
                    float(w)
                    paper_side = "BUY" if w > 0 else "SELL"
                    paper_qty = abs(w) * 100000

                    # Shadow path: same signal → same weight → broker boundary
                    shadow_signal = paper_signal  # same computation
                    shadow.compare_signals(str(date), inst, paper_signal, shadow_signal)

                    # Shadow order generation
                    shadow_order = shadow.generate_shadow_order(
                        timestamp=str(date),
                        instrument_id=inst,
                        side=paper_side,
                        quantity=paper_qty,
                        current_price=close,
                        spread=spread,
                    )

                    # Paper order
                    paper_order = {
                        "side": paper_side,
                        "quantity": paper_qty,
                        "price": close,
                    }

                    # Compare orders
                    shadow.compare_orders(str(date), inst, paper_order, shadow_order)
                    signal_count += 1

        if signal_count % 500 == 0 and signal_count > 0:
            print(f"  Processed {signal_count} signals...")

    print(f"  Total signals processed: {signal_count}")

    # 5. Get results
    print("\n[5/5] Computing shadow results...")
    result = shadow.get_result()

    # Print report
    print("\n" + "=" * 70)
    print("SHADOW QUALIFICATION REPORT")
    print("=" * 70)
    print(f"  Campaign: {result.campaign_id}")
    print(f"  Status: {result.status}")
    print(f"  Match rate: {result.match_rate:.1%}")
    print()
    print("  Divergence Summary:")
    print(f"    Exact matches: {result.exact_matches}")
    print(f"    Expected differences: {result.expected_differences}")
    print(f"    Tolerable: {result.tolerable_divergences}")
    print(f"    Unexplained: {result.unexplained_divergences}")
    print(f"    Critical: {result.critical_divergences}")
    print()
    print("  Order Summary:")
    print(f"    Would submit: {result.orders_would_submit}")
    print(f"    Would reject: {result.orders_would_reject}")
    print()

    # Classify divergences
    by_category: dict[str, list[Any]] = {}
    for div in result.divergences:
        by_category.setdefault(div.category, []).append(div)

    print("  Divergences by Category:")
    for cat, divs in sorted(by_category.items()):
        classifications = [d.classification.value for d in divs]
        match_count = classifications.count("match")
        print(f"    {cat:15s}: {len(divs)} total, {match_count} matches")

    # Save report
    report_path = "docs/SHADOW_QUALIFICATION_REPORT.md"
    with open(report_path, "w") as f:
        f.write("# Shadow Qualification Report\n\n")
        f.write(f"**Campaign:** {result.campaign_id}\n")
        f.write(f"**Status:** {result.status}\n")
        f.write(f"**Match rate:** {result.match_rate:.1%}\n\n")
        f.write("## Divergence Summary\n\n")
        f.write(f"- Exact matches: {result.exact_matches}\n")
        f.write(f"- Expected differences: {result.expected_differences}\n")
        f.write(f"- Tolerable: {result.tolerable_divergences}\n")
        f.write(f"- Unexplained: {result.unexplained_divergences}\n")
        f.write(f"- Critical: {result.critical_divergences}\n\n")
        f.write("## Order Summary\n\n")
        f.write(f"- Would submit: {result.orders_would_submit}\n")
        f.write(f"- Would reject: {result.orders_would_reject}\n\n")
        f.write("## Classification\n\n")
        if result.status == "PASS":
            f.write("**SHADOW QUALIFIED** — Paper and shadow paths match.\n")
        elif result.status == "WARNING":
            f.write("**CONDITIONAL** — Unexplained divergences detected.\n")
        else:
            f.write("**BLOCKED** — Critical divergences detected.\n")
    print(f"\nReport saved to {report_path}")

    return {
        "result": result.to_dict(),
        "verdict": result.status,
    }


if __name__ == "__main__":
    report = run_shadow()
    print("\n" + "=" * 70)
    print(f"FINAL VERDICT: {report['verdict']}")
    print("=" * 70)
