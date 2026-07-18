import logging
import statistics
import time

logger = logging.getLogger("eigencapital.benchmark_service")


class BenchmarkService:
    def __init__(self, engine):
        self.engine = engine

    def record_cycle(self, t0: float, t1: float, t2: float, t3: float) -> None:
        elapsed = time.perf_counter() - t0
        self.engine._cycle_times.append(elapsed)
        if len(self.engine._cycle_times) > self.engine._cycle_times_maxlen:
            self.engine._cycle_times = self.engine._cycle_times[-self.engine._cycle_times_maxlen :]

        if len(self.engine._cycle_times) % 20 == 0:
            recent = self.engine._cycle_times[-100:]
            p50 = statistics.median(recent)
            p95 = sorted(recent)[int(len(recent) * 0.95)]
            logger.info(
                "BENCHMARK: cycle=%.3fs  orch=%.3fs  narr=%.3fs  rebal=%.3fs  p50=%.3fs  p95=%.3fs  n=%d",
                elapsed,
                t1 - t0,
                t2 - t1,
                t3 - t2,
                p50,
                p95,
                len(recent),
            )
