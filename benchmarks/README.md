# Hot-Path Microbenchmark

A standalone, network-independent harness that exercises the full
feature-build → inference → state-write hot path with synthetic data.

## Quick start

```sh
# Smoke test (1 asset, 1 worker, dummy models)
python benchmarks/microbenchmark.py --quick

# Full portfolio (22 assets, 8 workers, 10 warm cycles)
python benchmarks/microbenchmark.py --quick --assets 22 --workers 8 --cycles 10

# Sweep the asset × worker grid
python benchmarks/microbenchmark.py --quick --sweep

# Profile one cycle (dumps .prof for snakeviz / gprof2dot)
python benchmarks/microbenchmark.py --quick --profile /tmp/cycle.prof
```

## Reference numbers (2026-05, commit c7f9eed)

| Assets | Workers | Warm p50 (s) | Per-asset (ms) | Speedup vs 1w |
|--------|---------|--------------|----------------|----------------|
| 1      | 1       | 0.15         | 152            | —              |
| 5      | 1       | 0.68         | 136            | 1.0×           |
| 5      | 4       | 0.66         | 132            | 1.03×          |
| 10     | 1       | 1.55         | 155            | 1.0×           |
| 10     | 8       | 1.12         | 112            | 1.39×          |
| 22     | 8       | 1.63         | 109            | —              |

The GIL ceiling is visible at 10+ assets — parallelism tops out at
~1.4× regardless of worker count.  **8 workers is optimal** for the
current workload mix.

## Production estimate

Add ~1s for batched HTTP (yfinance).  Expected cycle time on a 5-minute
cadence: **~2.6s p50, <5s p95**.  Safety margin > 300× at the compute
floor.

## Known ceilings

- **Parallelism:** GIL contention caps speedup at ~1.4×.  Moving beyond
  8 workers does not help (and may hurt via thread scheduling overhead).
- **Feature build:** `build_alpha_features` is ~80% of per-asset time.
  Cross-asset macro feature sharing would save ~25ms/asset (23% of
  portfolio time).  Worth revisiting when portfolio > 20 assets.
- **Cold cycle:** First cycle is always slower (TTLCache fill, PSI
  baseline, inference validation).  Allow 1 extra cycle before
  steady-state.

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--assets` | 22 | Number of assets (subset of config YAML) |
| `--workers` | 8 | ThreadPoolExecutor workers |
| `--cycles` | 5 | Warm cycles after cold run |
| `--bars` | 500 | Synthetic OHLCV rows per asset |
| `--quick` | off | Skip full training; use dummy XGBoost |
| `--sweep` | off | Run asset × worker grid sequentially |
| `--profile` | "" | Write cProfile `.prof` file for one cycle |
| `--skip-validation` | off | Force inference truncation on |
| `--output` | "" | Path to write JSONL results |
