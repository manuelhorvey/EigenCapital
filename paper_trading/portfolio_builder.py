import logging

from features.registry import FEATURE_REGISTRY
from paper_trading.config_manager import get_config

logger = logging.getLogger("quantforge.portfolio_builder")


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
            config = spec.get("config", {})
            sl_mult = spec.get("sl_mult", 1.0)
            tp_mult = spec.get("tp_mult", 2.5)
            pf[name] = {
                "ticker": ticker,
                "contract": contract,
                "alloc": alloc,
                "halt": halt,
                "config": config,
                "sl_mult": sl_mult,
                "tp_mult": tp_mult,
                "regime_geometry": regime_geom,
            }
        return pf
    return {
        "NZDJPY": {
            "ticker": "NZDJPY=X",
            "contract": FEATURE_REGISTRY["NZDJPY=X"],
            "alloc": 0.11,
            "halt": {
                "drawdown": -0.06,
                "monthly_pf": 0.70,
                "signal_drought": 30,
                "prob_drift": 0.15,
            },
            "config": {},
        },
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
        "GBPJPY": {
            "ticker": "GBPJPY=X",
            "contract": FEATURE_REGISTRY["GBPJPY=X"],
            "alloc": 0.06,
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
        "GBPUSD": {
            "ticker": "GBPUSD=X",
            "contract": FEATURE_REGISTRY["GBPUSD=X"],
            "alloc": 0.04,
            "halt": dict(halt_defaults),
            "config": {},
        },
    }
