"""Monte Carlo Diagnostics — R1 research package.

R1 Phase A delivers the trade-stream persistence boundary: a deterministic,
provenance-stamped sequence of closed trades that Monte Carlo diagnostics
(permutation/shuffle, bootstrap, block bootstrap) consume as their sole input.

R1 Phase B1 adds the trade-sequence permutation diagnostic: permute the ORDER
of the historical trades, rebuild each equity path, and compare the observed
path against the distribution of alternative orderings of the SAME trades.

See docs/research/R0_INFRASTRUCTURE_VERIFICATION.md (PATCH item),
docs/research/R1_MONTE_CARLO.md (Phases A/B), and
docs/research/RESEARCH_LITERATURE_AUDIT_REVIEW.md §9 (R1 definition).

Scope guard (frozen review §14): this package is research-only. It never
modifies R4, the risk engine, or execution.
"""

from eigencapital.research.monte_carlo.adapter import (
    backtest_results_to_trade_stream,
)
from eigencapital.research.monte_carlo.block_bootstrap import (
    BlockBootstrapResult,
    HistoricalBlockSample,
    moving_block_sample,
    run_block_bootstrap_test,
)
from eigencapital.research.monte_carlo.bootstrap import (
    BootstrapResult,
    HistoricalSample,
    run_bootstrap_test,
)
from eigencapital.research.monte_carlo.evidence import (
    EvidenceReport,
    MetricComparison,
    build_evidence_report,
    render_markdown,
)
from eigencapital.research.monte_carlo.path_metrics import (
    PathMetrics,
    compute_path_metrics,
    trade_pnls,
)
from eigencapital.research.monte_carlo.permutation import (
    HistoricalPath,
    PermutationResult,
    run_permutation_test,
)
from eigencapital.research.monte_carlo.persistence import (
    load_trade_stream,
    save_trade_stream,
)
from eigencapital.research.monte_carlo.schema import (
    TradeRecord,
    TradeStream,
    TradeStreamError,
)

__all__ = [
    "TradeRecord",
    "TradeStream",
    "TradeStreamError",
    "load_trade_stream",
    "save_trade_stream",
    "backtest_results_to_trade_stream",
    "PathMetrics",
    "compute_path_metrics",
    "trade_pnls",
    "HistoricalPath",
    "PermutationResult",
    "run_permutation_test",
    "BootstrapResult",
    "HistoricalSample",
    "run_bootstrap_test",
    "BlockBootstrapResult",
    "HistoricalBlockSample",
    "moving_block_sample",
    "run_block_bootstrap_test",
    "EvidenceReport",
    "MetricComparison",
    "build_evidence_report",
    "render_markdown",
]
