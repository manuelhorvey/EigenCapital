"""DOE sweep definitions — configurable experiment grids.

Label strategy versions:
    TB_v1      — production asymmetric triple barrier (pt>sl)
    TB_v2      — alternative asymmetric triple barrier
    TB_sym     — symmetric triple barrier (pt=sl)
    TB_wide    — wide symmetric (pt=sl=1.0, fewer timeouts)
    Meta_v1    — direction + meta-labeling
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Iterator


@dataclass
class LabelExperiment:
    asset: str
    label_method: str = "triple_barrier"
    label_strategy_version: str = "TB_v1"
    pt: float = 2.0
    sl: float = 2.0
    vb: int = 20
    vol_method: str | None = None
    atr_period: int | None = None

    @property
    def experiment_id(self) -> str:
        from research.label_optimization.schema import experiment_id
        return experiment_id(self.asset, self.label_method, self.pt, self.sl, self.vb)

    @property
    def pt_sl(self) -> list[float]:
        return [self.pt, self.sl]


@dataclass
class DOEGrid:
    assets: list[str]
    pts: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0, 4.0])
    sls: list[float] | None = None
    vbs: list[int] = field(default_factory=lambda: [20])
    vol_methods: list[str | None] = field(default_factory=lambda: [None])
    atr_periods: list[int | None] = field(default_factory=lambda: [None])
    strategy_version: str = "TB_v1"

    def __post_init__(self):
        if self.sls is None:
            self.sls = self.pts

    def experiments(self) -> Iterator[LabelExperiment]:
        for asset, (pt, sl), vb, vm, ap in product(
            self.assets, zip(self.pts, self.sls), self.vbs,
            self.vol_methods, self.atr_periods,
        ):
            yield LabelExperiment(
                asset=asset, pt=pt, sl=sl, vb=vb,
                vol_method=vm, atr_period=ap,
                label_strategy_version=self.strategy_version,
            )


# ---------- Stage A: Sentinel assets for rapid iteration ----------

SENTINEL_ASSETS = ["EURCHF", "GC", "DJI"]

# Phase 1a: symmetric PT=SL sweep (establishes imbalance vs. performance)
STAGE_A_SYMMETRIC = DOEGrid(
    assets=SENTINEL_ASSETS,
    pts=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    sls=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    vbs=[20],
    strategy_version="TB_sym",
)

# Phase 1b: asymmetric PT>SL (production regime, isolate bias)
STAGE_A_ASYMMETRIC_PT = DOEGrid(
    assets=SENTINEL_ASSETS,
    pts=[2.0, 3.0, 4.0, 5.0, 6.0],
    sls=[1.0],
    vbs=[20],
    strategy_version="TB_v1",
)

# Phase 1c: asymmetric SL>PT (inverted, diagnostic)
STAGE_A_ASYMMETRIC_SL = DOEGrid(
    assets=SENTINEL_ASSETS,
    pts=[1.0],
    sls=[2.0, 3.0, 4.0, 5.0, 6.0],
    vbs=[20],
    strategy_version="TB_v2",
)

# Quick version for testing the framework
STAGE_A_QUICK = DOEGrid(
    assets=SENTINEL_ASSETS,
    pts=[1.0, 2.0, 3.0, 4.0],
    sls=[1.0, 2.0, 3.0, 4.0],
    vbs=[20],
    strategy_version="TB_sym",
)


# ---------- Stage B: Full 17-asset sweep ----------

ALL_ASSETS = [
    "EURCHF", "GC", "DJI", "USDCAD", "AUDUSD",
    "USDJPY", "EURUSD", "GBPUSD", "NZDUSD", "GBPCAD",
    "CADCHF", "EURAUD", "GBPCHF", "NZDCHF", "NZDCAD",
    "AUDCAD", "EURJPY",
]

STAGE_B_SYMMETRIC = DOEGrid(
    assets=ALL_ASSETS,
    pts=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    sls=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    vbs=[20],
    strategy_version="TB_sym",
)

STAGE_B_QUICK = DOEGrid(
    assets=ALL_ASSETS,
    pts=[1.0, 2.0, 3.0, 4.0],
    sls=[1.0, 2.0, 3.0, 4.0],
    vbs=[20],
    strategy_version="TB_sym",
)


# ---------- Stage C: Hold-out assets (not optimized against) ----------

HOLDOUT_ASSETS = ["XAGUSD", "XAUUSD", "USDMXN"]

STAGE_C_VALIDATION = DOEGrid(
    assets=HOLDOUT_ASSETS,
    pts=[1.0, 2.0, 3.0, 4.0],
    sls=[1.0, 2.0, 3.0, 4.0],
    vbs=[20],
    strategy_version="TB_sym",
)


# ---------- The experiment the user specifically asked for ----------

# Symmetric labels + unchanged execution. Train with PT=SL, then evaluate
# using the production execution engine (same position sizing, exits, etc.).
# This isolates whether the classifier benefits from balanced learning
# even if the trading logic still targets asymmetric payoffs.
SYMMETRIC_SENTINEL = [
    LabelExperiment(asset=a, pt=2.0, sl=2.0, vb=20, label_strategy_version="TB_sym")
    for a in SENTINEL_ASSETS
]
