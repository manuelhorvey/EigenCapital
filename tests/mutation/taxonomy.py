"""L1–L8 Leakage Taxonomy — operational spec for temporal correctness.

Each class defines:
    - detection_rule:   assertion or invariant that catches this class
    - invariant:        the invariant violated
    - canonical_example: real-world occurrence from the codebase
    - forbidden:        patterns that must never appear
    - approved:         patterns that satisfy the invariant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar


class Severity(Enum):
    CRITICAL = auto()
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


class LeakageClass(str, Enum):
    """Enum of all L-classes for lookup in test markers and CI gates."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"
    L8 = "L8"


@dataclass(frozen=True)
class TaxonomyEntry:
    """Single L-class specification."""

    id: LeakageClass
    name: str
    severity: Severity
    description: str
    detection_rule: str
    invariant: str
    canonical_example: str
    forbidden: list[str] = field(default_factory=list)
    approved: list[str] = field(default_factory=list)

    def marker_name(self) -> str:
        return f"leakage_{self.id.value.lower()}"


TAXONOMY: dict[LeakageClass, TaxonomyEntry] = {
    LeakageClass.L1: TaxonomyEntry(
        id=LeakageClass.L1,
        name="Explicit future indexing",
        severity=Severity.CRITICAL,
        description="Code references future rows directly (e.g. .iloc[i+1], .shift(-1)).",
        detection_rule="Permute data[t:] → feature_row(t) must be invariant",
        invariant="I1: future independence — feature(t) depends only on data[:t]",
        canonical_example="features/alpha_features.py:23-24 — global .quantile() on full series",
        forbidden=[
            ".iloc[i + N] with N > 0",
            ".shift(-N) with N > 0",
            ".bfill() before train/test split",
            ".reindex(method='bfill')",
        ],
        approved=[
            ".shift(N) with N > 0 for lag features",
            ".rolling(N).mean() for causal rolling stats",
            ".expanding().quantile() for causal quantile clipping",
        ],
    ),
    LeakageClass.L2: TaxonomyEntry(
        id=LeakageClass.L2,
        name="Global normalization / statistics",
        severity=Severity.CRITICAL,
        description="Mean, std, quantile, min, max computed on the full dataset before splitting.",
        detection_rule="Truncate data to [:t] → feature(t) from truncated == feature(t) from full",
        invariant="I2: truncation invariance — estimate at t uses only data[:t]",
        canonical_example="features/alpha_features.py:23 — carry_to_vol.quantile([0.05, 0.95]) on full series",
        forbidden=[
            ".mean() on full series",
            ".std() on full series",
            ".quantile() on full series",
            ".min() / .max() on full series",
            "sklearn.preprocessing.StandardScaler.fit(X)",
        ],
        approved=[
            ".expanding().mean() for causal location shift",
            ".expanding().std() for causal scale shift",
            ".expanding().quantile() for causal clipping",
            "sklearn.preprocessing.StandardScaler.fit(X_train)",
        ],
    ),
    LeakageClass.L3: TaxonomyEntry(
        id=LeakageClass.L3,
        name="Forward-fill across embargo boundary",
        severity=Severity.HIGH,
        description="ffill or interpolation that crosses the train/test split, leaking future info into training.",
        detection_rule="Embargo gap must contain NaN; ffill must not bridge the gap",
        invariant="I3: embargo purity — no observation in train set depends on test-set data",
        canonical_example="paper_trading/inference/pipeline.py:64 — df['close'] = df['close'].ffill() on full history",
        forbidden=[
            ".ffill() on full dataset before split",
            ".interpolate() on full dataset before split",
            ".fillna(method='ffill') on concatenated train+test",
        ],
        approved=[
            ".ffill() within each training fold only",
            ".reindex(method='ffill') bounded by fold boundaries",
        ],
    ),
    LeakageClass.L4: TaxonomyEntry(
        id=LeakageClass.L4,
        name="Timestamp truncation / timezone destruction",
        severity=Severity.HIGH,
        description=(
            "TZ-aware timestamps stripped to naive dates, collapsing session"
            " boundaries and destroying ordering precision."
        ),
        detection_rule="All DatetimeIndexes must be tz-aware; .date conversion is forbidden",
        invariant="I6: timestamp provenance — every index carries unambiguous tz-aware timestamps",
        canonical_example="features/data_fetch.py:15 — s.index = pd.to_datetime(s.index.date)",
        forbidden=[
            ".index.date",
            ".tz_convert('UTC').date",
            "tz_localize(None)",
            "pd.to_datetime(index.date)",
        ],
        approved=[
            ".tz_convert('UTC').normalize()",
            ".tz_localize('UTC') for naive indexes",
        ],
    ),
    LeakageClass.L5: TaxonomyEntry(
        id=LeakageClass.L5,
        name="Distribution hindsight leakage",
        severity=Severity.HIGH,
        description=(
            "Feature parameters (clipping bounds, scaling factors) depend on"
            " full-data distribution, conditioning earlier rows on future states."
        ),
        detection_rule=(
            "Permute data[t:] → earlier distribution estimates unchanged;"
            " aka I1 applied to distributional stats"
        ),
        invariant="I2 (distributional form): quantile bounds, scaling factors at t must use data[:t] only",
        canonical_example="features/alpha_features.py:23 — global quantile clipping before expanding fix",
        forbidden=[
            "global quantile clipping (.quantile() on full series)",
            "fit scaler on full dataset",
            "global winsorization bounds",
        ],
        approved=[
            ".expanding().quantile() for causal clipping",
            "rolling window quantiles",
            "fit scaler on training fold only",
        ],
    ),
    LeakageClass.L6: TaxonomyEntry(
        id=LeakageClass.L6,
        name="Feature-schema drift",
        severity=Severity.MEDIUM,
        description="Column names, dtypes, or ordering change across runs or folds, breaking model portability.",
        detection_rule="Schema hash (col_names + dtypes) must be invariant under identical params",
        invariant="I7: schema stability — identical parameters produce identical column sets",
        canonical_example="None detected yet (potential hazard after feature addition)",
        forbidden=[
            "dynamic column names based on data values",
            "non-deterministic feature ordering",
            "dtype changes between train and inference",
        ],
        approved=[
            "fixed column schema per model version",
            "strict dtype casting on output",
        ],
    ),
    LeakageClass.L7: TaxonomyEntry(
        id=LeakageClass.L7,
        name="Numerical instability edge case",
        severity=Severity.LOW,
        description=(
            "Division by zero, log of zero, NaN propagation in feature computation"
            " that creates undefined or silent incorrect values."
        ),
        detection_rule="Feature outputs must be finite or explicitly NaN for unstable inputs",
        invariant="I8: numerical robustness — no silent NaN, Inf, or zero-divide in feature tensors",
        canonical_example="features/alpha_features.py:22 — realized_vol.replace(0, np.nan) before division",
        forbidden=[
            "/ realized_vol without .replace(0, np.nan)",
            'np.log(0) or np.log(negative) without clip',
            "np.sqrt(negative)",
        ],
        approved=[
            ".replace(0, np.nan) before division",
            ".clip(lower=1e-8) before log",
            ".clip(lower=0) before sqrt",
        ],
    ),
    LeakageClass.L8: TaxonomyEntry(
        id=LeakageClass.L8,
        name="Replay nondeterminism",
        severity=Severity.MEDIUM,
        description="Same input data + same seed produces different feature outputs across runs.",
        detection_rule="Identical inputs + identical seeds → identical feature output (bitwise)",
        invariant="I9: deterministic reproducibility — F(data, seed) = F(data, seed) for all calls",
        canonical_example="None detected yet (potential hazard after parallel execution migration)",
        forbidden=[
            "global RNG without explicit seed",
            "datetime.now() or time.time() in feature computation",
            "thread_id or process_id in hash computation",
            "non-deterministic sort of columns",
        ],
        approved=[
            "explicit np.random.default_rng(seed) per call",
            "seed stored in feature config and logged",
        ],
    ),
}


def lookup(class_id: str | LeakageClass) -> TaxonomyEntry:
    if isinstance(class_id, str):
        class_id = LeakageClass(class_id.upper())
    return TAXONOMY[class_id]


def leakage_marker_names() -> list[str]:
    return [e.marker_name() for e in TAXONOMY.values()]


# Constant for CI gating: any test with these markers MUST fail in mutation mode
MUTATION_REQUIRED_MARKERS: ClassVar[list[str]] = leakage_marker_names()
