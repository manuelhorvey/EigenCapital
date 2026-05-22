"""Regime-Conditional Geometry Tuning.

Generates per-asset, per-regime SL/TP multipliers based on
plateau-optimized base configs + regime performance adjustments.

Key insight from surface analysis:
  - high_vol: usually best regime → use base or widen
  - low_vol:  usually good      → use base
  - transition: often worst     → tighten or skip

Usage:
    from research.execution_surface.regime_geometry import get_regime_config, tune_all

    config = get_regime_config('NZDJPY')
    # returns ReplayRegimeConfig with asset-specific tuned geometry
"""

import os, sys, json, logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

logger = logging.getLogger("quantforge.execution_surface.regime_geom")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SANDBOX_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            'data', 'sandbox')

# Default regime geometry configs (generic, used as fallback)
DEFAULT_RECIME_GEOM = {
    'low_vol':    {'sl_mult': 0.52, 'tp_mult': 1.96},
    'transition': {'sl_mult': 0.65, 'tp_mult': 1.65},
    'high_vol':   {'sl_mult': 0.75, 'tp_mult': 1.50},
}

# Assets that should skip certain regimes entirely
SKIP_RECIMES = {
    'NZDJPY': {'transition'},
}

# Per-asset tuned regime geometries (derived from plateau + regime outcome data)
# Format: {asset: {regime: {sl_mult, tp_mult}}}
# Values are adjustments relative to the asset's plateau center.
TUNED_GEOMETRIES = {
    'NZDJPY': {
        'low_vol':    None,              # use plateau base
        'high_vol':   None,              # use plateau base (Avg R 0.53, good)
        'transition': {'sl_mult': 0.40, 'tp_mult': 1.20},  # tighten hard (Avg R -0.12)
    },
    'GC': {
        'high_vol':   None,              # use plateau base (Avg R 0.83, great)
        'low_vol':    {'sl_mult': 0.40, 'tp_mult': 2.00},  # tighten SL (Avg R 0.15)
        'transition': {'sl_mult': 0.40, 'tp_mult': 1.80},  # tighten both (Avg R 0.26)
    },
    'EURCAD': {
        'high_vol':   {'sl_mult': 0.60, 'tp_mult': 2.20},  # widen (Avg R 0.70)
        'low_vol':    None,              # use base (Avg R 0.29)
        'transition': {'sl_mult': 0.40, 'tp_mult': 1.60},  # tighten (Avg R 0.25)
    },
    'USDCHF': {
        'low_vol':    None,              # use base (Avg R 0.54, best)
        'high_vol':   {'sl_mult': 0.40, 'tp_mult': 1.60},  # tighten (Avg R 0.19)
        'transition': {'sl_mult': 0.45, 'tp_mult': 1.80},  # tighten (Avg R 0.41)
    },
    'DJI': {
        'low_vol':    {'sl_mult': 0.40, 'tp_mult': 1.50},  # tighten all (all weak)
        'high_vol':   {'sl_mult': 0.40, 'tp_mult': 1.50},
        'transition': {'sl_mult': 0.35, 'tp_mult': 1.40},
    },
    'GBPUSD': None,  # use plateau center for all regimes (consistent ~0.31-0.58)
    'AUDJPY': {
        'high_vol':   None,              # Avg R 0.42
        'low_vol':    {'sl_mult': 0.45, 'tp_mult': 1.80},  # tighten slightly (Avg R 0.31)
    },
    'USDCAD': {
        'high_vol':   None,              # Avg R 0.32
        'low_vol':    None,              # Avg R 0.42 (best)
        'transition': {'sl_mult': 0.45, 'tp_mult': 1.70},  # tighten (Avg R 0.25)
    },
}


def get_plateau_center(name: str) -> Optional[dict]:
    """Load plateau center from aggregate report."""
    report_path = os.path.join(SANDBOX_BASE, 'sltp_analysis', 'aggregate_report.json')
    if not os.path.exists(report_path):
        return None
    with open(report_path) as f:
        report = json.load(f)
    r = report.get(name, {})
    if 'error' in r:
        return None
    plateau = r.get('plateau', {})
    if plateau and 'error' not in plateau:
        return {
            'sl_mult': plateau.get('center_sl_mult', 0.75),
            'tp_mult': plateau.get('center_tp_mult', 2.25),
        }
    bs = r.get('best_sharpe', {})
    if bs:
        return {'sl_mult': bs.get('sl_mult', 0.75), 'tp_mult': bs.get('tp_mult', 2.25)}
    return None


def apply_regime_adjustment(base_sl: float, base_tp: float,
                            regime_adjust: Optional[dict]) -> tuple:
    """Apply a regime-specific geometry override.

    If regime_adjust is None, use base geometry.
    Otherwise, the adjustment dict contains sl_mult and tp_mult values
    that OVERRIDE (not scale) the base values.
    """
    if regime_adjust is None:
        return base_sl, base_tp
    return regime_adjust['sl_mult'], regime_adjust['tp_mult']


def build_regime_config(name: str, plateau: Optional[dict] = None) -> dict:
    """Build a per-asset regime geometry config dict.

    Returns:
        dict with:
            regime_geom: {regime: {sl_mult, tp_mult}}
            default_geom: {sl_mult, tp_mult}
            skip_regimes: set of regimes to skip
    """
    if plateau is None:
        plateau = get_plateau_center(name)
    if plateau is None:
        plateau = {'sl_mult': 0.75, 'tp_mult': 2.25}

    base_sl = plateau['sl_mult']
    base_tp = plateau['tp_mult']

    asset_tuning = TUNED_GEOMETRIES.get(name)
    skip = SKIP_RECIMES.get(name, set())

    if asset_tuning is None:
        # No per-regime tuning — use plateau base for all regimes
        regime_geom = {
            regime: {'sl_mult': base_sl, 'tp_mult': base_tp}
            for regime in ['low_vol', 'high_vol', 'transition']
        }
    else:
        regime_geom = {}
        for regime in ['low_vol', 'high_vol', 'transition']:
            adj = asset_tuning.get(regime)
            sl, tp = apply_regime_adjustment(base_sl, base_tp, adj)
            regime_geom[regime] = {'sl_mult': sl, 'tp_mult': tp}

    return {
        'regime_geom': regime_geom,
        'default_geom': {'sl_mult': base_sl, 'tp_mult': base_tp},
        'skip_regimes': skip,
    }


def tune_all() -> dict:
    """Generate and save tuned regime configs for all assets."""
    from research.execution_surface.replay_engine import ReplayRegimeConfig

    report_path = os.path.join(SANDBOX_BASE, 'sltp_analysis', 'aggregate_report.json')
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
    else:
        report = {}

    configs = {}
    for name in sorted(report.keys()):
        if 'error' in report.get(name, {}):
            continue
        cfg = build_regime_config(name)
        configs[name] = cfg
        skip_info = f' skip={cfg["skip_regimes"]}' if cfg['skip_regimes'] else ''
        logger.info('%s: base(sl=%.2f, tp=%.2f)  low(sl=%.2f, tp=%.2f)  high(sl=%.2f, tp=%.2f)  trans(sl=%.2f, tp=%.2f)%s',
                    name,
                    cfg['default_geom']['sl_mult'], cfg['default_geom']['tp_mult'],
                    cfg['regime_geom'].get('low_vol', {}).get('sl_mult', 0),
                    cfg['regime_geom'].get('low_vol', {}).get('tp_mult', 0),
                    cfg['regime_geom'].get('high_vol', {}).get('sl_mult', 0),
                    cfg['regime_geom'].get('high_vol', {}).get('tp_mult', 0),
                    cfg['regime_geom'].get('transition', {}).get('sl_mult', 0),
                    cfg['regime_geom'].get('transition', {}).get('tp_mult', 0),
                    skip_info)

    out_path = os.path.join(SANDBOX_BASE, 'regime_geometries.json')
    with open(out_path, 'w') as f:
        json.dump(configs, f, indent=2, default=str)
    logger.info('Saved regime geometries to %s', out_path)

    return configs


def to_replay_config(name: str, regime_cfg: Optional[dict] = None) -> 'ReplayRegimeConfig':
    """Convert a regime config dict to a ReplayRegimeConfig dataclass."""
    from research.execution_surface.replay_engine import ReplayRegimeConfig

    if regime_cfg is None:
        regime_cfg = build_regime_config(name)

    return ReplayRegimeConfig(
        regime_geom=regime_cfg['regime_geom'],
        default_geom=regime_cfg['default_geom'],
        skip_regimes=regime_cfg['skip_regimes'],
    )


def main():
    configs = tune_all()
    print(f'\nGenerated {len(configs)} regime configs')
    for name, cfg in sorted(configs.items()):
        print(f'  {name}: default(sl={cfg["default_geom"]["sl_mult"]:.2f}, tp={cfg["default_geom"]["tp_mult"]:.2f})'
              f'  skip={cfg["skip_regimes"]}')


if __name__ == '__main__':
    main()
