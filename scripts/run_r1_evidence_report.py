"""R1-B4 Evidence Report Runner — combined B1/B2/B3 diagnostics for R4.

Loads the persisted R4 trade stream, runs all three resampling diagnostics
with recorded seeds, and emits ONE evidence artifact in two forms:
    reports/r1_monte_carlo/r1_evidence_report.json
    reports/r1_monte_carlo/r1_evidence_report.md

B3 block length is PRE-SPECIFIED here (a deliberate methodological choice,
recorded in the artifact) — it is not tuned and no alternative sizes are
searched. B4 is aggregation only: no new methodology, no pass/fail.

Usage:
    python scripts/run_r1_evidence_report.py [--stream PATH] [--block-length N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

from eigencapital.research.monte_carlo.block_bootstrap import run_block_bootstrap_test
from eigencapital.research.monte_carlo.bootstrap import run_bootstrap_test
from eigencapital.research.monte_carlo.evidence import build_evidence_report, render_markdown
from eigencapital.research.monte_carlo.permutation import run_permutation_test
from eigencapital.research.monte_carlo.persistence import load_trade_stream

DEFAULT_STREAM = "reports/r1_monte_carlo/trade_stream_R4_daily.json"
DEFAULT_BLOCK_LENGTH = 20  # pre-specified: ≈ 4 weeks of daily round-trips
N_ITERATIONS = 1000
SEED = 42


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the R1-B4 combined evidence report")
    parser.add_argument("--stream", default=DEFAULT_STREAM)
    parser.add_argument(
        "--block-length",
        type=int,
        default=DEFAULT_BLOCK_LENGTH,
        help="PRE-SPECIFIED B3 block length (not tuned; recorded in the artifact)",
    )
    parser.add_argument("--out-dir", default="reports/r1_monte_carlo")
    args = parser.parse_args()

    stream = load_trade_stream(args.stream)
    print(f"Loaded stream: {stream.stream_id} ({len(stream.trades)} trades)")
    print(f"B3 block length (pre-specified): {args.block_length}")

    b1 = run_permutation_test(stream, n_permutations=N_ITERATIONS, seed=SEED)
    b2 = run_bootstrap_test(stream, n_resamples=N_ITERATIONS, seed=SEED)
    b3 = run_block_bootstrap_test(stream, block_length=args.block_length, n_resamples=N_ITERATIONS, seed=SEED)
    print("Diagnostics complete: B1 permutation, B2 IID bootstrap, B3 moving-block bootstrap")

    report = build_evidence_report(stream=stream, permutation=b1, bootstrap=b2, block_bootstrap=b3)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "r1_evidence_report.json"
    md_path = out_dir / "r1_evidence_report.md"
    json_path.write_text(__import__("json").dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Artifact written: {json_path}")
    print(f"Artifact written: {md_path}")

    print("\nHeadline (experiment-percentiles, NOT probabilities):")
    for line in report.interpretation:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
