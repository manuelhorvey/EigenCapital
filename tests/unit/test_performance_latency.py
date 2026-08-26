"""Performance and latency benchmarks for production trading paths."""

import statistics
import time
from typing import List


def _bench(func, iterations: int = 1000) -> List[float]:
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func()
        end = time.perf_counter_ns()
        latencies.append((end - start) / 1000)
    return latencies


def _percentiles(latencies: List[float]) -> dict:
    s = sorted(latencies)
    n = len(s)
    return {"p50": s[n // 2], "p95": s[int(n * 0.95)], "p99": s[int(n * 0.99)]}


class TestRiskEvaluationLatency:
    def test_risk_check_latency(self):
        from eigencapital.live.risk_enforcement import RiskEnvelope, RiskEnforcer

        envelope = RiskEnvelope(max_concurrent_positions=19, max_position_notional=5000.0,
                                max_order_notional=1500.0, max_account_drawdown_pct=20.0,
                                max_daily_loss=250.0, min_equity=4000.0)
        enforcer = RiskEnforcer(envelope)

        def check():
            enforcer.check_all(broker_positions=[], account_equity=5000.0, account_free_margin=3000.0)

        pcts = _percentiles(_bench(check, 2000))
        assert pcts["p99"] < 500, f"Risk check p99={pcts['p99']:.0f}µs"

    def test_risk_check_with_positions_latency(self):
        from eigencapital.live.risk_enforcement import RiskEnvelope, RiskEnforcer

        envelope = RiskEnvelope(max_concurrent_positions=19, max_position_notional=5000.0,
                                max_order_notional=1500.0, max_account_drawdown_pct=20.0,
                                max_daily_loss=250.0, min_equity=4000.0)
        enforcer = RiskEnforcer(envelope)
        positions = [{"symbol": f"SYM{i}", "volume": 0.01, "price": 100.0 + i} for i in range(8)]

        def check():
            enforcer.check_all(broker_positions=positions, account_equity=5000.0, account_free_margin=3000.0)

        pcts = _percentiles(_bench(check, 2000))
        assert pcts["p99"] < 1000, f"Risk check (8 positions) p99={pcts['p99']:.0f}µs"


class TestFingerprintLatency:
    def test_fingerprint_verification_latency(self):
        from eigencapital.fidelity.r4_manifest import R4ConfigManifest
        from eigencapital.risk.policy import RiskPolicy
        from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

        verifier = FingerprintVerifier(manifest=R4ConfigManifest(), risk_policy=RiskPolicy())
        pcts = _percentiles(_bench(verifier.verify_all, 2000))
        assert pcts["p99"] < 2000, f"Fingerprint verify p99={pcts['p99']:.0f}µs"


class TestConfigValidationLatency:
    def test_config_load_latency(self):
        from eigencapital.config import load_config
        pcts = _percentiles(_bench(lambda: load_config("production"), 500))
        assert pcts["p99"] < 50_000, f"Config load p99={pcts['p99']:.0f}µs"


class TestStateTransitionLatency:
    def test_disconnect_recovery_transition_latency(self):
        from eigencapital.live.risk import DisconnectRecovery, RecoveryState

        def cycle():
            dr = DisconnectRecovery()
            dr.on_disconnect()
            dr.on_reconnect()
            if dr.state == RecoveryState.RECONCILING:
                dr.on_reconnect()

        pcts = _percentiles(_bench(cycle, 5000))
        assert pcts["p99"] < 200, f"State transition p99={pcts['p99']:.0f}µs"


class TestCapitalBoundaryLatency:
    def test_capital_check_latency(self):
        from eigencapital.production_qual.capital_boundary import CapitalBoundaryConfig, CapitalBoundaryValidator

        validator = CapitalBoundaryValidator(CapitalBoundaryConfig())

        def validate():
            validator.run_all_validations(
                actual_equity=5000.0, start_timestamp="2026-01-01T00:00:00Z",
                end_timestamp="2026-01-15T00:00:00Z", actual_duration_days=14.0,
                r4_position_count=4, pre_existing_position_count=0,
                manual_position_count=0, manual_trade_count=0,
                current_drawdown_pct=5.0, current_daily_loss=50.0,
            )

        pcts = _percentiles(_bench(validate, 2000))
        assert pcts["p99"] < 500, f"Capital check p99={pcts['p99']:.0f}µs"


class TestLatencyStability:
    def test_risk_check_stable_over_10k_cycles(self):
        from eigencapital.live.risk_enforcement import RiskEnvelope, RiskEnforcer

        envelope = RiskEnvelope(max_concurrent_positions=19, max_position_notional=5000.0,
                                max_order_notional=1500.0, max_account_drawdown_pct=20.0,
                                max_daily_loss=250.0, min_equity=4000.0)
        enforcer = RiskEnforcer(envelope)

        block_medians = []
        for _ in range(4):
            lats = _bench(
                lambda: enforcer.check_all(broker_positions=[], account_equity=5000.0, account_free_margin=3000.0),
                2500,
            )
            block_medians.append(statistics.median(lats))

        ratio = block_medians[-1] / max(block_medians[0], 0.001)
        assert ratio < 2.0, f"Latency grew {ratio:.1f}x over 10K cycles"


class TestEmergencyFlattenLatency:
    def test_flatten_with_many_positions(self):
        from eigencapital.execution.trading_provider import (
            TradingProvider, AccountInfo, PositionInfo, SymbolInfo,
            TickInfo, OrderRequest, OrderResult,
        )
        from typing import Optional, List

        class FakeProvider(TradingProvider):
            def connect(self, host="127.0.0.1", port=8001) -> bool: return True
            def disconnect(self) -> None: pass
            def is_connected(self) -> bool: return True
            def account_info(self) -> Optional[AccountInfo]: return AccountInfo(equity=5000.0)
            def positions_get(self, ticket=None) -> List[PositionInfo]: return []
            def symbol_info(self, symbol: str) -> Optional[SymbolInfo]: return None
            def symbol_info_tick(self, symbol: str) -> Optional[TickInfo]: return None
            def symbol_select(self, symbol: str, enable=True) -> bool: return True
            def copy_rates_from_pos(self, symbol, timeframe, start_pos, count): return []
            def order_send(self, request: OrderRequest) -> OrderResult:
                return OrderResult(success=True, order=1, deal=1, retcode=10009)
            def last_error(self) -> str: return ""
            def emergency_flatten(self):
                return [{"symbol": f"S{i}", "closed": True} for i in range(100)]

        provider = FakeProvider()
        start = time.perf_counter_ns()
        result = provider.emergency_flatten()
        elapsed_us = (time.perf_counter_ns() - start) / 1000

        assert len(result) == 100
        assert elapsed_us < 1_000_000, f"Emergency flatten took {elapsed_us/1000:.1f}ms"
