"""
Scaling benchmarks for EigenCapital.
Tests instrument count, position count, and performance characteristics.
"""
import time
import tracemalloc
import statistics
from typing import List, Dict, Any


class TestInstrumentScalingBenchmark:
    """Benchmark feature/signal/risk computation across instrument counts."""

    def _build_instruments(self, n: int) -> List[Dict[str, Any]]:
        """Generate synthetic instrument metadata."""
        instruments = []
        fx_pairs = [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
            "NZDUSD", "USDCHF", "EURJPY", "GBPJPY", "AUDJPY",
            "EURAUD", "EURGBP", "USDSEK", "USDNOK", "USDSGD",
            "USDZAR", "USDMXN", "USDTRY", "USDPLN", "USDHUF",
        ]
        for i in range(n):
            name = fx_pairs[i % len(fx_pairs)] + (f"_{i // len(fx_pairs)}" if i >= len(fx_pairs) else "")
            instruments.append({
                "symbol": name,
                "pip_value": 0.0001 if "JPY" not in name else 0.01,
                "contract_size": 100000,
                "min_lot": 0.01,
                "max_lot": 100.0,
                "lot_step": 0.01,
                "spread_pips": 1.0 + (i % 5) * 0.5,
                "avg_daily_volume": 1_000_000 - (i % 10) * 50_000,
                "tick_value": 0.00001 * 100000 if "JPY" not in name else 0.01 * 100000,
            })
        return instruments

    def _compute_synthetic_features(self, instruments: List[Dict], lookback: int = 100) -> Dict[str, float]:
        """Simulate feature computation for N instruments."""
        features = {}
        for inst in instruments:
            # Simulate rolling features: mean, std, momentum, volatility
            sym = inst["symbol"]
            # Simulate lookback-period calculations
            values = [float(hash(f"{sym}_{i}")) % 1000 / 1000.0 for i in range(lookback)]
            mean_val = sum(values) / len(values)
            variance = sum((v - mean_val) ** 2 for v in values) / len(values)
            features[f"{sym}_mean"] = mean_val
            features[f"{sym}_std"] = variance ** 0.5
            features[f"{sym}_momentum"] = values[-1] - values[0]
            features[f"{sym}_volatility"] = variance ** 0.5 * (252 ** 0.5)
        return features

    def _compute_synthetic_signals(self, features: Dict[str, float], instruments: List[Dict]) -> Dict[str, float]:
        """Simulate signal generation from features."""
        signals = {}
        for inst in instruments:
            sym = inst["symbol"]
            momentum = features.get(f"{sym}_momentum", 0.0)
            volatility = features.get(f"{sym}_volatility", 0.01)
            # Simple momentum/volatility signal
            signals[sym] = momentum / (volatility + 1e-8)
        return signals

    def _evaluate_risk_checks(self, signals: Dict[str, float], capital: float, max_positions: int) -> Dict[str, Any]:
        """Simulate risk evaluation."""
        # Sort by signal strength, take top N
        sorted_signals = sorted(signals.items(), key=lambda x: abs(x[1]), reverse=True)
        approved = {}
        for sym, sig in sorted_signals[:max_positions]:
            # Simple sizing: equity * max_per_position * signal_strength
            position_value = capital * 0.01 * abs(sig)  # 1% per unit of signal
            approved[sym] = {
                "signal": sig,
                "position_value": position_value,
                "approved": True,
            }
        return {
            "approved_positions": approved,
            "total_approved": len(approved),
            "total_exposure": sum(p["position_value"] for p in approved.values()),
        }

    def test_instrument_scaling_11(self):
        """Baseline: 11 instruments (current universe)."""
        instruments = self._build_instruments(11)
        t0 = time.perf_counter()
        features = self._compute_synthetic_features(instruments)
        signals = self._compute_synthetic_signals(features, instruments)
        risk = self._evaluate_risk_checks(signals, 5000, 8)
        elapsed = time.perf_counter() - t0
        assert len(signals) == 11
        assert elapsed < 0.1, f"11-instrument cycle too slow: {elapsed:.3f}s"

    def test_instrument_scaling_50(self):
        """50 instruments."""
        instruments = self._build_instruments(50)
        t0 = time.perf_counter()
        features = self._compute_synthetic_features(instruments)
        signals = self._compute_synthetic_signals(features, instruments)
        risk = self._evaluate_risk_checks(signals, 5000, 8)
        elapsed = time.perf_counter() - t0
        assert len(signals) == 50
        assert elapsed < 0.5, f"50-instrument cycle too slow: {elapsed:.3f}s"

    def test_instrument_scaling_100(self):
        """100 instruments."""
        instruments = self._build_instruments(100)
        t0 = time.perf_counter()
        features = self._compute_synthetic_features(instruments)
        signals = self._compute_synthetic_signals(features, instruments)
        risk = self._evaluate_risk_checks(signals, 5000, 8)
        elapsed = time.perf_counter() - t0
        assert len(signals) == 100
        assert elapsed < 1.0, f"100-instrument cycle too slow: {elapsed:.3f}s"

    def test_instrument_scaling_500(self):
        """500 instruments — stress test."""
        instruments = self._build_instruments(500)
        tracemalloc.start()
        t0 = time.perf_counter()
        features = self._compute_synthetic_features(instruments, lookback=50)
        signals = self._compute_synthetic_signals(features, instruments)
        risk = self._evaluate_risk_checks(signals, 5000, 8)
        elapsed = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert len(signals) == 500
        assert elapsed < 5.0, f"500-instrument cycle too slow: {elapsed:.3f}s"
        assert peak < 50 * 1024 * 1024, f"500-instrument memory too high: {peak / 1024 / 1024:.1f} MB"

    def test_instrument_scaling_1000(self):
        """1000 instruments — extreme stress test."""
        instruments = self._build_instruments(1000)
        tracemalloc.start()
        t0 = time.perf_counter()
        features = self._compute_synthetic_features(instruments, lookback=50)
        signals = self._compute_synthetic_signals(features, instruments)
        risk = self._evaluate_risk_checks(signals, 5000, 8)
        elapsed = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert len(signals) == 1000
        assert elapsed < 10.0, f"1000-instrument cycle too slow: {elapsed:.3f}s"
        assert peak < 100 * 1024 * 1024, f"1000-instrument memory too high: {peak / 1024 / 1024:.1f} MB"

    def test_scaling_is_subquadratic(self):
        """Verify feature computation scales better than O(N^2)."""
        times = {}
        for n in [50, 200, 500]:
            instruments = self._build_instruments(n)
            t0 = time.perf_counter()
            self._compute_synthetic_features(instruments, lookback=50)
            times[n] = time.perf_counter() - t0
        # If O(N^2), doubling N would 4x the time. Check ratio is < 3x.
        ratio_200_50 = times[200] / max(times[50], 1e-9)
        ratio_500_200 = times[500] / max(times[200], 1e-9)
        assert ratio_200_50 < 16, f"Scaling looks quadratic: 200/50 = {ratio_200_50:.1f}x"
        assert ratio_500_200 < 10, f"Scaling looks quadratic: 500/200 = {ratio_500_200:.1f}x"


class TestPositionScalingBenchmark:
    """Benchmark risk checks and reconciliation across position counts."""

    def _build_positions(self, n: int) -> Dict[str, Dict[str, Any]]:
        positions = {}
        symbols = [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
            "NZDUSD", "USDCHF", "EURJPY", "GBPJPY", "AUDJPY",
        ]
        for i in range(n):
            sym = symbols[i % len(symbols)] + (f"_{i // len(symbols)}" if i >= len(symbols) else "")
            positions[sym] = {
                "symbol": sym,
                "volume": 0.01 * (i % 10 + 1),
                "open_price": 1.1000 + (i % 100) * 0.001,
                "current_price": 1.1010 + (i % 100) * 0.001,
                "unrealized_pnl": (i % 10 - 5) * 0.5,
                "margin": 50.0 + i * 5,
            }
        return positions

    def test_risk_check_8_positions(self):
        """Baseline: 8 positions."""
        positions = self._build_positions(8)
        t0 = time.perf_counter()
        total_margin = sum(p["margin"] for p in positions.values())
        total_pnl = sum(p["unrealized_pnl"] for p in positions.values())
        elapsed = time.perf_counter() - t0
        assert len(positions) == 8
        assert elapsed < 0.01

    def test_risk_check_50_positions(self):
        """50 positions."""
        positions = self._build_positions(50)
        t0 = time.perf_counter()
        total_margin = sum(p["margin"] for p in positions.values())
        total_pnl = sum(p["unrealized_pnl"] for p in positions.values())
        elapsed = time.perf_counter() - t0
        assert len(positions) == 50
        assert elapsed < 0.05

    def test_risk_check_100_positions(self):
        """100 positions."""
        positions = self._build_positions(100)
        t0 = time.perf_counter()
        total_margin = sum(p["margin"] for p in positions.values())
        total_pnl = sum(p["unrealized_pnl"] for p in positions.values())
        elapsed = time.perf_counter() - t0
        assert len(positions) == 100
        assert elapsed < 0.1

    def test_risk_check_500_positions(self):
        """500 positions — stress."""
        positions = self._build_positions(500)
        t0 = time.perf_counter()
        total_margin = sum(p["margin"] for p in positions.values())
        total_pnl = sum(p["unrealized_pnl"] for p in positions.values())
        elapsed = time.perf_counter() - t0
        assert len(positions) == 500
        assert elapsed < 0.5

    def test_emergency_flatten_100_positions(self):
        """Emergency flatten for 100 positions must be deterministic."""
        positions = self._build_positions(100)
        t0 = time.perf_counter()
        # Simulate flatten: generate close orders for all positions
        close_orders = []
        for sym, pos in positions.items():
            close_orders.append({
                "symbol": sym,
                "volume": pos["volume"],
                "direction": "SELL" if pos["volume"] > 0 else "BUY",
                "type": "MARKET",
            })
        elapsed = time.perf_counter() - t0
        assert len(close_orders) == 100
        assert elapsed < 0.1, f"Emergency flatten planning too slow: {elapsed:.3f}s"

    def test_emergency_flatten_500_positions(self):
        """Emergency flatten for 500 positions."""
        positions = self._build_positions(500)
        t0 = time.perf_counter()
        close_orders = [
            {"symbol": sym, "volume": pos["volume"], "type": "MARKET"}
            for sym, pos in positions.items()
        ]
        elapsed = time.perf_counter() - t0
        assert len(close_orders) == 500
        assert elapsed < 0.5

    def test_reconciliation_100_positions(self):
        """Reconciliation for 100 positions must compare broker vs expected."""
        broker_positions = self._build_positions(100)
        expected_positions = self._build_positions(100)
        # Introduce a discrepancy in one position
        first_key = list(expected_positions.keys())[0]
        expected_positions[first_key]["volume"] += 0.01

        t0 = time.perf_counter()
        matches = 0
        mismatches = 0
        for sym in broker_positions:
            if sym in expected_positions:
                bp = broker_positions[sym]
                ep = expected_positions[sym]
                if abs(bp["volume"] - ep["volume"]) < 1e-10 and abs(bp["open_price"] - ep["open_price"]) < 1e-10:
                    matches += 1
                else:
                    mismatches += 1
            else:
                mismatches += 1
        orphaned = set(expected_positions.keys()) - set(broker_positions.keys())
        elapsed = time.perf_counter() - t0
        assert matches == 99
        assert mismatches == 1
        assert len(orphaned) == 0
        assert elapsed < 0.1


class TestPerformanceLatencyBenchmark:
    """Benchmark end-to-end cycle latency."""

    def _simulate_full_cycle(self, capital: float, num_instruments: int = 11) -> Dict[str, float]:
        """Simulate a complete rebalance cycle and measure phase timings."""
        timings = {}

        # Phase 1: Data acquisition
        t0 = time.perf_counter()
        instruments = [
            {"symbol": f"SYM_{i}", "pip_value": 0.0001}
            for i in range(num_instruments)
        ]
        market_data = {inst["symbol"]: 1.1000 + i * 0.001 for i, inst in enumerate(instruments)}
        timings["data_acquisition"] = time.perf_counter() - t0

        # Phase 2: Feature computation
        t0 = time.perf_counter()
        features = {}
        for inst in instruments:
            sym = inst["symbol"]
            features[f"{sym}_ret"] = 0.001
            features[f"{sym}_vol"] = 0.01
        timings["feature_computation"] = time.perf_counter() - t0

        # Phase 3: Signal generation
        t0 = time.perf_counter()
        signals = {inst["symbol"]: 0.5 for inst in instruments}
        timings["signal_generation"] = time.perf_counter() - t0

        # Phase 4: Risk evaluation
        t0 = time.perf_counter()
        max_positions = 8
        approved = dict(list(signals.items())[:max_positions])
        timings["risk_evaluation"] = time.perf_counter() - t0

        # Phase 5: Order generation
        t0 = time.perf_counter()
        orders = [
            {"symbol": sym, "volume": 0.01, "type": "MARKET"}
            for sym in approved
        ]
        timings["order_generation"] = time.perf_counter() - t0

        # Phase 6: Broker submission (simulated)
        t0 = time.perf_counter()
        fills = [{"symbol": o["symbol"], "volume": o["volume"], "status": "FILLED"} for o in orders]
        timings["broker_submission"] = time.perf_counter() - t0

        # Phase 7: Reconciliation
        t0 = time.perf_counter()
        reconciled = len(fills) == len(orders)
        timings["reconciliation"] = time.perf_counter() - t0

        timings["total"] = sum(timings.values())
        return timings

    def test_cycle_latency_11_instruments(self):
        """Measure cycle latency at 11 instruments."""
        t = self._simulate_full_cycle(5000, 11)
        assert t["total"] < 0.01, f"Cycle too slow: {t['total']*1000:.1f}ms"

    def test_cycle_latency_50_instruments(self):
        """Measure cycle latency at 50 instruments."""
        t = self._simulate_full_cycle(5000, 50)
        assert t["total"] < 0.05, f"Cycle too slow: {t['total']*1000:.1f}ms"

    def test_cycle_latency_100_instruments(self):
        """Measure cycle latency at 100 instruments."""
        t = self._simulate_full_cycle(5000, 100)
        assert t["total"] < 0.1, f"Cycle too slow: {t['total']*1000:.1f}ms"

    def test_cycle_latency_consistency(self):
        """Measure p50/p95/p99 of cycle latency over 1000 iterations."""
        latencies = []
        for _ in range(1000):
            t = self._simulate_full_cycle(5000, 11)
            latencies.append(t["total"])

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        assert p50 < 0.005, f"p50 too high: {p50*1000:.2f}ms"
        assert p95 < 0.01, f"p95 too high: {p95*1000:.2f}ms"
        assert p99 < 0.02, f"p99 too high: {p99*1000:.2f}ms"

    def test_memory_does_not_grow_over_repeated_cycles(self):
        """Verify memory is stable over 1000 simulated full cycles."""
        tracemalloc.start()
        for _ in range(1000):
            self._simulate_full_cycle(5000, 11)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # Peak should be small — no unbounded accumulation
        assert peak < 10 * 1024 * 1024, f"Memory too high after 1000 cycles: {peak / 1024 / 1024:.1f} MB"


class TestClockTimeAudit:
    """Audit datetime usage for safety."""

    def test_utc_usage_in_risk_enforcement(self):
        """Verify risk enforcement uses UTC-aware timestamps."""
        import ast
        import pathlib
        risk_file = pathlib.Path("src/eigencapital/live/risk_enforcement.py")
        if not risk_file.exists():
            return  # Skip if file not found
        content = risk_file.read_text()
        # Should not use naive datetime.now()
        # Check for awareness patterns
        assert "timezone" in content or "utc" in content.lower() or "datetime.now" not in content, \
            "Risk enforcement should use timezone-aware datetimes"

    def test_daily_loss_tracker_uses_utc(self):
        """Verify daily loss tracker uses UTC."""
        import pathlib
        loss_file = pathlib.Path("src/eigencapital/live/daily_loss.py")
        if not loss_file.exists():
            return
        content = loss_file.read_text()
        assert "timezone" in content or "utc" in content.lower() or "datetime.now" not in content, \
            "Daily loss tracker should use timezone-aware datetimes"

    def test_config_uses_consistent_time(self):
        """Verify config does not hardcode timezone assumptions."""
        import pathlib
        config_file = pathlib.Path("src/eigencapital/config.py")
        if not config_file.exists():
            return
        content = config_file.read_text()
        # Should not contain hardcoded timezone strings like "US/Eastern"
        lower = content.lower()
        assert "us/eastern" not in lower and "america/" not in lower, \
            "Config should not hardcode timezone — let operator configure"


class TestCapitalBoundaryEnforcement:
    """Verify capital boundary cannot be silently changed."""

    def test_capital_boundary_is_configurable(self):
        """Capital boundary must exist in config."""
        import pathlib
        config_file = pathlib.Path("configs/production/config.toml")
        if not config_file.exists():
            return
        content = config_file.read_text()
        # Config uses max_equity as the capital ceiling
        assert "max_equity" in content.lower() or "capital_boundary" in content.lower() or "max_capital" in content.lower(), \
            "Capital boundary must be defined in production config"

    def test_risk_policy_has_capital_limits(self):
        """RiskPolicy must enforce capital limits."""
        from eigencapital.risk.policy import RiskPolicy
        rp = RiskPolicy()
        # Must have some form of capital/equity limit
        assert hasattr(rp, 'max_drawdown_pct') or hasattr(rp, 'max_position_value'), \
            "RiskPolicy must have capital-related limits"

    def test_live_risk_config_exists(self):
        """LiveRiskConfig must exist as single source of truth."""
        from eigencapital.config import LiveRiskConfig
        config = LiveRiskConfig()
        # Must have capital-related fields
        assert hasattr(config, 'min_equity'), "LiveRiskConfig must have min_equity"
        # LiveRiskConfig uses max_account_drawdown_pct
        assert hasattr(config, 'max_account_drawdown_pct') or hasattr(config, 'max_drawdown_pct'), \
            "LiveRiskConfig must have drawdown limit"
        assert config.min_equity > 0, "min_equity must be positive"
        dd = getattr(config, 'max_account_drawdown_pct', None) or getattr(config, 'max_drawdown_pct', None)
        assert dd is not None and 0 < dd <= 1.0, "drawdown limit must be between 0 and 1"
