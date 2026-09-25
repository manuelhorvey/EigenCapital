"""Evidence accounting: comparison counters, families, verdict formatting.

Implements the brief's multiple-testing discipline for descriptive work:
every pairwise/statistical comparison executed anywhere in this package
increments a declared counter; inferential p-values are Holm-corrected
inside their pre-declared family; missing evidence yields INCONCLUSIVE
(RESEARCH_ACCOUNTING_CONTRACT fail-closed rule).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from research.volatility import config as C

SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT SUPPORTED"
INCONCLUSIVE = "INCONCLUSIVE"
STABLE = "STABLE"
UNSTABLE = "UNSTABLE"
STRUCTURALLY_DISTINCT = "STRUCTURALLY DISTINCT"
STRUCTURALLY_REDUNDANT = "STRUCTURALLY REDUNDANT"
INSUFFICIENT_DATA = "INSUFFICIENT DATA"


@dataclass
class EvidenceLedger:
    """Trial-accounting-style ledger for descriptive comparisons."""

    comparisons: dict[str, int] = field(default_factory=dict)
    clustering_configurations: int = 0
    candidate_evaluations: int = 0
    loo_evaluations: int = 0
    hypothesis_tests: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def count(self, key: str, n: int = 1) -> None:
        self.comparisons[key] = self.comparisons.get(key, 0) + n

    def record_test(
        self, family: str, name: str, p_raw: float | None, statistic: float | None, verdict: str, detail: str = ""
    ) -> None:
        self.hypothesis_tests.setdefault(family, {})[name] = {
            "p_raw": p_raw,
            "statistic": statistic,
            "verdict": verdict,
            "detail": detail,
        }

    @property
    def total_comparisons(self) -> int:
        return sum(self.comparisons.values())

    def family_size(self, family: str) -> int:
        return C.H_FAMILIES.get(family, len(self.hypothesis_tests.get(family, {})))

    def holm_correct(self, family: str) -> None:
        """Apply Holm step-down to every p_raw recorded in the family."""
        tests = self.hypothesis_tests.get(family, {})
        named = {k: v for k, v in tests.items() if v.get("p_raw") is not None}
        if not named:
            return
        m = len(named)
        ordered = sorted(named.items(), key=lambda kv: kv[1]["p_raw"])
        running_max = 0.0
        for i, (name, rec) in enumerate(ordered):
            adj = min(1.0, rec["p_raw"] * (m - i))
            running_max = max(running_max, adj)
            rec["p_holm"] = running_max
            rec["holm_threshold"] = 0.05
        self.count(f"holm_families:{family}", 1)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_comparisons"] = self.total_comparisons
        return d


LEDGER = EvidenceLedger()


def spearman_with_p(x, y) -> tuple[float, float]:
    """Spearman rho + two-sided p; (nan, nan) if degenerate."""
    import numpy as np
    from scipy import stats

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < C.MIN_CELL_TRADES:
        return float("nan"), float("nan")
    rho, p = stats.spearmanr(x[m], y[m])
    return float(rho), float(p)
