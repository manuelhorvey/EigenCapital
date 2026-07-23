"""DOE sweep definitions — configurable experiment grids."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Iterator


@dataclass
class LabelExperiment:
    """Single experiment configuration."""
    asset: str
    label_method: str = "triple_barrier"
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
    """Design of Experiments — generates cartesian product of parameters per asset."""
    assets: list[str]
    pts: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0, 4.0])
    sls: list[float] | None = None           # None = symmetric (same as pt)
    vbs: list[int] = field(default_factory=lambda: [20])
    vol_methods: list[str | None] = field(default_factory=lambda: [None])
    atr_periods: list[int | None] = field(default_factory=lambda: [None])

    def __post_init__(self):
        if self.sls is None:
            self.sls = self.pts

    def experiments(self) -> Iterator[LabelExperiment]:
        for asset, (pt, sl), vb, vm, ap in product(
            self.assets,
            zip(self.pts, self.sls),
            self.vbs,
            self.vol_methods,
            self.atr_periods,
        ):
            yield LabelExperiment(
                asset=asset,
                pt=pt,
                sl=sl,
                vb=vb,
                vol_method=vm,
                atr_period=ap,
            )


# ---------- Phase 1: PT/SL sweep on representative assets ----------

PHASE1_ASSETS = ["EURCHF", "GC", "DJI"]

PHASE1_PTS = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
PHASE1_SLS = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
# Asymmetric: pt>sl (like production) vs symmetric (pt=sl)
# We'll generate both: symmetric (pt=sl) and asymmetric (pt>sl)
# The cartesian product covers all; we can filter later.

PHASE1_SYMMETRIC = DOEGrid(
    assets=PHASE1_ASSETS,
    pts=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    sls=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    vbs=[20],
)

# Phase 1b: asymmetric PT>SL sweeps (PT range, SL fixed at 1.0)
PHASE1_ASYMMETRIC_PT = DOEGrid(
    assets=PHASE1_ASSETS,
    pts=[2.0, 3.0, 4.0, 5.0, 6.0],
    sls=[1.0],
    vbs=[20],
)

# Phase 1c: asymmetric SL>PT sweeps (SL range, PT fixed at 1.0)
PHASE1_ASYMMETRIC_SL = DOEGrid(
    assets=PHASE1_ASSETS,
    pts=[1.0],
    sls=[2.0, 3.0, 4.0, 5.0, 6.0],
    vbs=[20],
)


# ---------- Phase 3: labeling method comparison ----------

PHASE3_ASSETS = ["EURCHF", "GC", "DJI", "USDCAD", "AUDUSD"]

# Fixed PT/SL for comparison
PHASE3_BASELINE_PT = 2.0
PHASE3_BASELINE_SL = 2.0

# We'll run the same PT/SL grid across different labeling methods
# (Future: add forward_return, meta_label, three_class)
PHASE3_METHODS = ["triple_barrier"]  # extend as methods are added


# ---------- Phase 4: vol method / barrier tests ----------

PHASE4_GRID = DOEGrid(
    assets=["EURCHF", "GC"],
    pts=[2.0],
    sls=[2.0],
    vbs=[10, 15, 20, 30, 40],
    vol_methods=[None, "atr"],
    atr_periods=[None, 14],
)
