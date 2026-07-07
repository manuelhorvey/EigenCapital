import logging

from features.registry import FEATURE_REGISTRY
from paper_trading.config_manager import get_config

logger = logging.getLogger("eigencapital.portfolio_builder")

# JPY-carry cluster: assets where JPY is the funding leg (short JPY)
JPY_CARRY_CLUSTER = {"NZDJPY", "CADJPY", "AUDJPY", "GBPJPY", "USDJPY", "CHFJPY"}
JPY_CARRY_MAX_ALLOC = 0.40  # 40% max total allocation to JPY crosses


def cluster_risk_report(portfolio: dict) -> list[str]:
    """Check portfolio for cluster concentration risks.

    Returns a list of warning strings (empty list = all clear).
    """
    warnings = []

    # JPY-carry cluster concentration
    jpy_total = 0.0
    jpy_assets = []
    for name, spec in portfolio.items():
        if name in JPY_CARRY_CLUSTER:
            alloc = spec.get("alloc", 0)
            jpy_total += alloc
            jpy_assets.append((name, alloc))

    if jpy_total > JPY_CARRY_MAX_ALLOC:
        warnings.append(
            f"JPY-carry cluster {jpy_total * 100:.0f}% exceeds limit "
            f"{JPY_CARRY_MAX_ALLOC * 100:.0f}% ({len(jpy_assets)} assets). "
            f"Consider reducing positions in: {', '.join(a for a, _ in jpy_assets)}"
        )

    return warnings


def build_paper_portfolio(halt_defaults: dict) -> dict:
    cfg = get_config()
    assets = cfg.assets
    regime_geom = cfg.regime_geometry
    if assets:
        pf = {}
        for name, spec in assets.items():
            ticker = spec.get("ticker", f"{name}")
            contract = FEATURE_REGISTRY.get(ticker)
            if contract is None:
                logger.warning("No contract for ticker %s; using config features", ticker)
                contract = type("Contract", (), {"features": spec.get("features", [])})()
            alloc = spec.get("allocation", 0)
            user_halt = spec.get("halt", {})
            halt = dict(halt_defaults)
            halt.update(user_halt)
            config = dict(spec.get("config", {}))
            defaults = cfg.defaults or {}
            if "churn_ratio_threshold" not in config:
                config["churn_ratio_threshold"] = defaults.get("churn_ratio_threshold", 0.50)
            narrative_cfg = cfg.narrative_config
            if narrative_cfg:
                config["narrative_config"] = narrative_cfg
            liquidity_cfg = cfg.liquidity_config
            if liquidity_cfg:
                config["liquidity_config"] = liquidity_cfg
            if spec.get("regime_sizing"):
                config["regime_sizing"] = True
                config.setdefault("vol_scalar", True)
            if spec.get("adaptive_macro"):
                config["adaptive_macro"] = True
            if "spread_tier" in spec:
                config["spread_tier"] = spec["spread_tier"]
            if "max_entry_slippage_pct" in spec:
                config["max_entry_slippage_pct"] = spec["max_entry_slippage_pct"]
            # Weekend config keys: propagate from config spec to per-asset config
            # so they are available to entry_service.py for weekend sizing logic.
            if "weekend_eligible" in spec:
                config["weekend_eligible"] = spec["weekend_eligible"]
            if "weekend_allocation_multiplier" in spec:
                config["weekend_allocation_multiplier"] = spec["weekend_allocation_multiplier"]
            baseline = cfg.vol_baselines.get(name)
            if baseline is not None:
                config["vol_baseline"] = baseline
            # max_positions_per_asset: per-asset override wins, then spec-level,
            # then global defaults, then SizingConfig default (2).
            if "max_positions_per_asset" not in config:
                config["max_positions_per_asset"] = int(
                    spec.get("max_positions_per_asset") or defaults.get("max_positions_per_asset", 2)
                )
            if "stacking" not in config:
                config["stacking"] = dict(defaults.get("stacking", {}))
            sl_mult = spec.get("sl_mult", 1.0)
            tp_mult = spec.get("tp_mult", 2.5)
            max_depth = spec.get("max_depth", 2)
            asset_regime_geom = spec.get("regime_geometry") or regime_geom
            pf[name] = {
                "ticker": ticker,
                "contract": contract,
                "alloc": alloc,
                "halt": halt,
                "config": config,
                "sl_mult": sl_mult,
                "tp_mult": tp_mult,
                "max_depth": max_depth,
                "regime_geometry": asset_regime_geom,
                "execution_config": spec.get("execution_config"),
            }
        return pf
    return {
        "CADJPY": {
            "ticker": "CADJPY=X",
            "contract": FEATURE_REGISTRY["CADJPY=X"],
            "alloc": 0.10,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "USDCAD": {
            "ticker": "USDCAD=X",
            "contract": FEATURE_REGISTRY["USDCAD=X"],
            "alloc": 0.07,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "GC": {
            "ticker": "GC=F",
            "contract": FEATURE_REGISTRY["GC=F"],
            "alloc": 0.15,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "EURAUD": {
            "ticker": "EURAUD=X",
            "contract": FEATURE_REGISTRY["EURAUD=X"],
            "alloc": 0.17,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "AUDJPY": {
            "ticker": "AUDJPY=X",
            "contract": FEATURE_REGISTRY["AUDJPY=X"],
            "alloc": 0.07,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "USDJPY": {
            "ticker": "USDJPY=X",
            "contract": FEATURE_REGISTRY["USDJPY=X"],
            "alloc": 0.05,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "USDCHF": {
            "ticker": "USDCHF=X",
            "contract": FEATURE_REGISTRY["USDCHF=X"],
            "alloc": 0.04,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "CHFJPY": {
            "ticker": "CHFJPY=X",
            "contract": FEATURE_REGISTRY["CHFJPY=X"],
            "alloc": 0.05,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "EURCAD": {
            "ticker": "EURCAD=X",
            "contract": FEATURE_REGISTRY["EURCAD=X"],
            "alloc": 0.04,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "EURUSD": {
            "ticker": "EURUSD=X",
            "contract": FEATURE_REGISTRY["EURUSD=X"],
            "alloc": 0.03,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "AUDUSD": {
            "ticker": "AUDUSD=X",
            "contract": FEATURE_REGISTRY["AUDUSD=X"],
            "alloc": 0.03,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "CL": {
            "ticker": "CL=F",
            "contract": FEATURE_REGISTRY["CL=F"],
            "alloc": 0.04,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "ES": {
            "ticker": "ES=F",
            "contract": FEATURE_REGISTRY["ES=F"],
            "alloc": 0.05,
            "halt": dict(halt_defaults),
            "config": {},
        },
        "NQ": {
            "ticker": "NQ=F",
            "contract": FEATURE_REGISTRY["NQ=F"],
            "alloc": 0.05,
            "halt": dict(halt_defaults),
            "config": {},
        },
    }
