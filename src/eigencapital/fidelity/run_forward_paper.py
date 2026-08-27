"""Run Forward Paper Campaign against live MT5 data.

This script:
1. Connects to MT5 via Wine bridge
2. Fetches the latest market data
3. Runs the frozen R4 configuration
4. Detects operational events
5. Produces the forward paper fidelity report
"""

from __future__ import annotations

import logging
from typing import Dict, Any

import numpy as np
import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.forward_campaign import (
    ForwardPaperCampaign,
)

logger = logging.getLogger(__name__)


def run_forward_paper() -> Dict[str, Any]:
    """Run forward paper campaign against live MT5 data."""
    print("=" * 70)
    print("FORWARD PAPER CAMPAIGN")
    print("Live MT5 Data + Frozen R4 Configuration")
    print("=" * 70)

    # 1. Load data
    print("\n[1/6] Loading MT5 data...")
    provider = MT5DataProvider()
    data, manifest = provider.load_from_csv()
    print(
        f"  Loaded {len(data)} symbols, {sum(len(df) for df in data.values())} total bars"
    )

    # 2. Create R4 manifest
    print("\n[2/6] Creating frozen R4 manifest...")
    r4_manifest = R4ConfigManifest(
        data_snapshot_hash=manifest.snapshot_hash,
        data_bar_count=manifest.bar_count,
    )
    print(f"  Manifest identity: {r4_manifest.compute_identity()[:16]}...")

    # 3. Initialize forward campaign
    print("\n[3/6] Initializing forward campaign...")
    campaign = ForwardPaperCampaign(r4_manifest)
    print(f"  Campaign ID: {campaign._campaign_id}")

    # 4. Process bars sequentially
    print("\n[4/6] Processing bars sequentially...")
    returns_df = pd.DataFrame(
        {
            sym: df["close"].pct_change()
            for sym, df in data.items()
            if "close" in df.columns
        }
    ).dropna(how="all")

    # Compute R4 weights
    mom_12m = (
        (1 + returns_df)
        .rolling(r4_manifest.signal_lookback_long)
        .apply(lambda x: x.prod() - 1, raw=True)
    )
    mom_1m = (
        (1 + returns_df)
        .rolling(r4_manifest.signal_lookback_short)
        .apply(lambda x: x.prod() - 1, raw=True)
    )
    signal = (mom_12m - mom_1m).dropna(how="all")
    ranks = signal.rank(axis=1, pct=True)
    base_weights = ranks - 0.5

    # Regime conditioning
    avg_vol = returns_df.rolling(r4_manifest.regime_vol_lookback).std().mean(
        axis=1
    ) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)
    rc_weights = base_weights.multiply(regime, axis=0)

    # Asset vol cap
    asset_vol = returns_df.rolling(60).std() * np.sqrt(252)
    vol_ratio = asset_vol / 0.50
    cap = np.minimum(vol_ratio, 1.0)
    vol_capped = rc_weights * cap

    # Crypto cap
    crypto_cols = [c for c in vol_capped.columns if "BTC" in c or "ETH" in c]
    crypto_capped = vol_capped.copy()
    for col in crypto_cols:
        if col in crypto_capped.columns:
            crypto_capped[col] = crypto_capped[col].clip(
                -r4_manifest.crypto_max_allocation,
                r4_manifest.crypto_max_allocation,
            )

    # Single asset cap
    final_weights = crypto_capped.clip(
        -r4_manifest.asset_risk_limit * 10,
        r4_manifest.asset_risk_limit * 10,
    )

    # Risk parity
    inv_vol = 1 / asset_vol.replace(0, np.nan)
    rp_weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0)

    # Blend
    combined = 0.7 * final_weights + 0.3 * rp_weights

    # Drawdown reducer
    port_ret = (combined.shift(1) * returns_df).sum(axis=1) / combined.abs().sum(
        axis=1
    ).replace(0, np.nan)
    port_ret = port_ret.dropna()
    cum = (1 + port_ret).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    in_dd = (dd < r4_manifest.drawdown_control_threshold).astype(float)
    scale = 1 - (in_dd * r4_manifest.drawdown_control_reduction)
    final = combined.multiply(scale, axis=0)

    # Process bars sequentially (simulating real-time)
    bar_count = 0
    for date in final.index:
        for inst in final.columns:
            w = final.loc[date, inst]
            if abs(w) > 1e-6 and inst in data:
                df = data[inst]
                if date in df.index:
                    row = df.loc[date]
                    campaign.ingest_bar(
                        {
                            "timestamp": str(date),
                            "instrument_id": inst,
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": float(row.get("volume", 0)),
                            "spread": 0.0002,  # simulated spread
                        }
                    )

                    # Make decision
                    sig = (
                        float(signal.loc[date, inst])
                        if inst in signal.columns and date in signal.index
                        else 0.0
                    )
                    campaign.make_decision(
                        timestamp=str(date),
                        instrument_id=inst,
                        signal=sig,
                        weight=float(w),
                        position=float(w * 100000),
                        order_intent="BUY" if w > 0 else "SELL" if w < 0 else "HOLD",
                        risk_approved=True,
                    )
                    bar_count += 1

        if bar_count % 500 == 0:
            print(f"  Processed {bar_count} bars...")

    print(f"  Total bars processed: {bar_count}")

    # 5. Get results
    print("\n[5/6] Computing results...")
    result = campaign.get_result()

    # 6. Evaluate fidelity
    print("\n[6/6] Evaluating fidelity...")
    fidelity_report = campaign.evaluate_fidelity()

    # Print report
    print("\n" + "=" * 70)
    print("FORWARD PAPER FIDELITY REPORT")
    print("=" * 70)
    print(fidelity_report.to_markdown())

    # Print operational summary
    state = result["operational_state"]
    print("\n" + "=" * 70)
    print("OPERATIONAL SUMMARY")
    print("=" * 70)
    print(f"  Total bars: {state['total_ticks']}")
    print(f"  Missing bars: {state['missing_bars']}")
    print(f"  Stale data events: {state['stale_data_events']}")
    print(f"  Spread widening events: {state['spread_widening_events']}")
    print(f"  Reconciliation checks: {state['reconciliation_checks']}")
    print(f"  Reconciliation failures: {state['reconciliation_failures']}")
    print(f"  Reconciliation success rate: {state['reconciliation_success_rate']:.1%}")
    print(f"  Error rate: {state['error_rate']:.2%}")
    print(f"  Max consecutive errors: {state['max_consecutive_errors']}")

    # Save report
    report_path = "docs/FORWARD_PAPER_FIDELITY_REPORT.md"
    with open(report_path, "w") as f:
        f.write(fidelity_report.to_markdown())
        f.write("\n\n## Operational Summary\n\n")
        f.write("```\n")
        for k, v in state.items():
            f.write(f"  {k}: {v}\n")
        f.write("```\n")
    print(f"\nReport saved to {report_path}")

    return {
        "result": result,
        "fidelity_report": fidelity_report.to_dict(),
        "verdict": fidelity_report.verdict.value,
    }


if __name__ == "__main__":
    report = run_forward_paper()
    print("\n" + "=" * 70)
    print(f"FINAL VERDICT: {report['verdict']}")
    print("=" * 70)
