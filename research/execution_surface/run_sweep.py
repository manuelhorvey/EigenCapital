#!/usr/bin/env python3
"""Orchestrator for the full execution surface mapping pipeline.

Usage:
    python -m research.execution_surface.run_sweep

Stages:
    1. freeze  — walk-forward OOS prediction freeze (one-time, ~45 min)
    2. mc      — Monte Carlo parameter sweep (~10 min)
    3. analyze — surface analysis + heatmaps (~1 min)

Run all stages sequentially:
    python -m research.execution_surface.run_sweep

Run individual stages:
    python -m research.execution_surface.run_sweep --stage freeze
    python -m research.execution_surface.run_sweep --stage mc
    python -m research.execution_surface.run_sweep --stage analyze

Run for a single asset:
    python -m research.execution_surface.run_sweep --assets BTC
"""

import sys, os, logging, argparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("quantforge.execution_surface")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.registry import FEATURE_REGISTRY
from research.execution_surface import prediction_freeze, monte_carlo, sltp_surface
from research.execution_surface.trade_outcome_analyzer import run_all as run_outcome_analysis


def resolve_tickers(asset_names):
    """Convert asset names (BTC, GC) to tickers (BTC-USD, GC=F)."""
    if not asset_names:
        return None
    name_to_ticker = {c.name: t for t, c in FEATURE_REGISTRY.items()}
    tickers = []
    for name in asset_names:
        if name in FEATURE_REGISTRY:
            tickers.append(name)
        elif name in name_to_ticker:
            tickers.append(name_to_ticker[name])
        else:
            logger.warning('Unknown asset: %s', name)
    return tickers if tickers else None


def main():
    parser = argparse.ArgumentParser(description='Execution surface mapping')
    parser.add_argument('--stage', choices=['freeze', 'mc', 'analyze', 'outcomes', 'all'],
                        default='all', help='Pipeline stage to run')
    parser.add_argument('--assets', nargs='+', help='Specific assets (e.g. BTC GC CADJPY)')
    parser.add_argument('--force', action='store_true', help='Re-run even if cached results exist')
    args = parser.parse_args()

    target_tickers = resolve_tickers(args.assets)
    if args.assets:
        logger.info('Targeting assets: %s → tickers: %s', args.assets, target_tickers)

    if args.stage in ('freeze', 'all'):
        logger.info('=' * 60)
        logger.info('STAGE 1: Prediction Freeze')
        logger.info('=' * 60)
        prediction_freeze.freeze_all(target_tickers=target_tickers, force=args.force)

    if args.stage in ('mc', 'all'):
        logger.info('=' * 60)
        logger.info('STAGE 2: Monte Carlo Sweep')
        logger.info('=' * 60)
        monte_carlo.sweep_all(force=args.force)

    if args.stage in ('analyze', 'all'):
        logger.info('=' * 60)
        logger.info('STAGE 3: Surface Analysis')
        logger.info('=' * 60)
        sltp_surface.analyze_all()

    if args.stage in ('outcomes', 'all'):
        logger.info('=' * 60)
        logger.info('STAGE 4: Trade Outcome Analysis')
        logger.info('=' * 60)
        run_outcome_analysis()

    logger.info('Done.')


if __name__ == '__main__':
    main()
