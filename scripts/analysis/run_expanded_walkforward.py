#!/usr/bin/env python3
"""Run walk-forward backtest on expanded 10+ year data with proper multi-regime coverage."""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("expanded_wf")

ASSETS = {
    "AUDJPY": "AUDJPY=X", "AUDUSD": "AUDUSD=X", "CADCHF": "CADCHF=X",
    "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X", "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURNZD": "EURNZD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X",
    "GBPJPY": "GBPJPY=X", "GBPUSD": "GBPUSD=X", "GC": "GC=F",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X",
    "NZDUSD": "NZDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X", "BTCUSD": "BTC-USD", "^DJI": "^DJI",
}


def main():
    logger.info("=" * 60)
    logger.info("Running expanded walk-forward backtest for all assets")
    logger.info("=" * 60)
    
    from scripts.backtest.walk_forward_backtest import run_walk_forward, _tag_path
    from paper_trading.config_manager import get_config
    from features.registry import ASSET_LABEL_PARAMS
    
    cfg = get_config()
    
    _asset_pt_sl = {}
    for name, acfg in cfg.assets.items():
        _tp = float(acfg.get("tp_mult", 2.0))
        _sl = float(acfg.get("sl_mult", 2.0))
        _asset_pt_sl[name] = (_tp, _sl)
    for name in ASSETS:
        if name not in _asset_pt_sl and name in ASSET_LABEL_PARAMS:
            _tp = ASSET_LABEL_PARAMS[name]["pt"]
            _sl = ASSET_LABEL_PARAMS[name]["sl"]
            _asset_pt_sl[name] = (_tp, _sl)
    
    btc_pt_sl = (2.5, 3.0)
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "walkforward")
    
    all_summaries = []
    
    for name, ticker in ASSETS.items():
        if ticker == "BTC-USD":
            pt_sl = btc_pt_sl
        else:
            pt_sl = _asset_pt_sl.get(name, (2.0, 2.0))
        
        # Load per-asset max_depth from production config
        acfg = cfg.assets.get(name, {})
        md = int(acfg.get("max_depth", 2))
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {name} ({ticker}) | pt_sl={pt_sl} | max_depth={md}")
        logger.info(f"{'='*60}")
        
        try:
            result = run_walk_forward(
                name, ticker,
                window_years=5,      # 5-year windows instead of 3
                step_years=2,        # 2-year steps (more overlap, more folds)
                n_folds=5,           # 5 folds for more regime coverage
                gap=20,
                ensemble_weight=1.0,  # base only (ensemble disabled)
                ensemble_threshold=0.15,
                pt_sl=pt_sl,
                max_depth=md,
                tag="expanded_10yr",
                window_type="expanding",
                rolling_window_bars=None,
                label_type="standard",
                invert_labels=False,
                sample_weight_flag=False,
                calibrate_flag=False,
                expanded_data_dir="auto",
            )
        except Exception as e:
            logger.error(f"{name}: FAILED with {e}")
            continue
        
        if result is not None:
            all_summaries.append(result)
            logger.info(f"{name}: done — {len(result)} folds, mean hit_rate={result['hit_rate'].mean():.3f}")
    
    if all_summaries:
        import pandas as pd
        combined = pd.concat(all_summaries)
        combined_path = os.path.join(OUTPUT_DIR, _tag_path("all_assets_wf_summary.csv", "expanded_10yr"))
        combined.to_csv(combined_path, index=False)
        logger.info(f"\nCombined summary -> {combined_path}")
        
        print("\n=== Cross-Asset Walk-Forward Summary (10yr Expanded) ===")
        metrics = ["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]
        avg = combined.groupby("asset")[metrics].mean()
        print(avg.to_string(float_format="%.3f"))
    
    logger.info("\nDone. Run validate_directional_skill.py --tag expanded_10yr to check directional skill.")


if __name__ == "__main__":
    main()
